from flask import Flask, render_template, jsonify, request
import database
import fetcher
import strategy
import settings as _settings
import history
import analysis

app = Flask(__name__)


@app.route("/")
def index():
    resp = app.make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/market")
def api_market():
    data = fetcher.get_all_market_data()
    gold_usd = data["gold_usd"]
    usd_toman = data["usd_toman"]
    gold_18k_toman = data["gold_18k_toman"]

    if not gold_usd or not usd_toman:
        return jsonify({"success": False, "error": "Could not fetch live market data"}), 503

    analysis = strategy.analyze(gold_usd, usd_toman, gold_18k_toman)

    portfolio = database.get_portfolio_summary()
    pnl = {}
    if portfolio["total_grams"] > 0:
        pnl = strategy.portfolio_pnl(portfolio, analysis["market_price_18k"])

    return jsonify(
        success=True,
        gold_usd=gold_usd,
        usd_toman=usd_toman,
        gold_18k_toman=gold_18k_toman,
        fetched_at=data["fetched_at"],
        sources_ok=data["sources_ok"],
        **analysis,
        portfolio=portfolio,
        pnl=pnl,
    )


@app.route("/api/trades", methods=["GET"])
def api_trades_get():
    return jsonify(database.get_all_trades())


@app.route("/api/trades", methods=["POST"])
def api_trades_post():
    body = request.json or {}

    weight = float(body.get("weight_grams", 0))
    price_per_gram = float(body.get("price_per_gram_toman", 0))
    if weight <= 0 or price_per_gram <= 0:
        return jsonify({"success": False, "error": "Invalid weight or price"}), 400

    total_cost = weight * price_per_gram

    trade_id = database.record_trade(
        weight_grams=weight,
        price_per_gram_toman=price_per_gram,
        total_cost_toman=total_cost,
        gold_usd_at_time=body.get("gold_usd"),
        usd_toman_at_time=body.get("usd_toman"),
        baseline_dollar_at_time=body.get("baseline_dollar"),
        intrinsic_value_at_time=body.get("intrinsic_value"),
        deviation_pct_at_time=body.get("deviation_pct"),
        signal_at_time=body.get("signal"),
        notes=body.get("notes", ""),
    )
    return jsonify({"success": True, "trade_id": trade_id, "total_cost": total_cost})


@app.route("/api/trades/<int:trade_id>", methods=["PATCH"])
def api_trade_update(trade_id: int):
    body = request.json or {}
    status = body.get("status")
    if status not in ("holding", "sold", "partial"):
        return jsonify({"success": False, "error": "Invalid status"}), 400
    database.update_trade_status(trade_id, status)
    return jsonify({"success": True})


@app.route("/settings")
def settings_page():
    resp = app.make_response(render_template("settings.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(_settings.load())


@app.route("/api/settings", methods=["PUT"])
def api_settings_put():
    body = request.json or {}
    # Validate and coerce types
    allowed = {
        "year_start_dollar":       (int,   1_000,   10_000_000),
        "annual_inflation_pct":    (float, 0.1,     500.0),
        "use_auto_growth":         (bool,  None,    None),
        "monthly_growth_manual":   (int,   100,     500_000),
        "optimistic_multiplier":   (float, 0.1,     10.0),
        "realistic_multiplier":    (float, 0.1,     10.0),
        "conservative_multiplier": (float, 0.1,     10.0),
        "gold_target_eoy_usd":     (float, 0,       50_000),
        "min_rr_ratio":            (float, 0.5,     20.0),
        "shamsi_year":             (int,   1380,    1450),
    }
    current = _settings.load()
    for key, (typ, lo, hi) in allowed.items():
        if key in body:
            try:
                val = typ(body[key])
                if lo is not None and hi is not None:
                    val = max(lo, min(hi, val))
                current[key] = val
            except (TypeError, ValueError):
                pass
    _settings.save(current)
    return jsonify({"success": True, "settings": current})


@app.route("/history")
def history_page():
    resp = app.make_response(render_template("history.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/history/fetch", methods=["POST"])
def api_history_fetch():
    try:
        stats = history.fetch_and_store_all()
        database.cache_delete("correlation_analysis")   # force recompute with new data
        return jsonify({"success": True, **stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history/status")
def api_history_status():
    status = database.get_historical_status()
    return jsonify(status)


@app.route("/api/analysis/correlation")
def api_analysis_correlation():
    cached = database.cache_get("correlation_analysis", max_age_seconds=3600)
    if cached:
        return jsonify(cached)
    result = analysis.run_correlation()
    if "error" not in result:
        database.cache_set("correlation_analysis", result)
    return jsonify(result)


if __name__ == "__main__":
    database.init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
