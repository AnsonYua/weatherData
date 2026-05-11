# Hong Kong Weather Polymarket Forecasting Model

This project is intended to build a forecasting and betting-analysis system for Hong Kong temperature markets on Polymarket.

The core goal is to use Hong Kong Observatory (HKO) forecast data and observed daily maximum temperature data to estimate probabilities for possible temperature outcomes, then compare those probabilities against Polymarket prices to identify positive expected value opportunities.

## Data Inputs

- Forecast JSON files from `weatherMake/gemma_json`
- Observed daily maximum temperature data from `max_data.csv`
- Forecast issue time from each JSON file's `report_datetime`

The forecast JSON data includes structured fields such as forecasted minimum and maximum temperature, humidity range, rain probability, wind description, weather text, weekday, and `weather_type`.

## Model Output

The model should estimate a probability distribution over possible highest-temperature outcomes for the target date.

The first practical output should be the top 3 likely temperature outcomes, for example:

```text
28°C: 42%
29°C: 31%
27°C: 18%
```

These probabilities can then be compared with Polymarket's market-implied probabilities.

## Betting Logic

The betting layer should compare the model probability with the market price.

For example, if the model estimates:

```text
28°C = 50%
```

and Polymarket's Yes price is:

```text
42¢
```

then the estimated edge is roughly:

```text
50% - 42% = +8 percentage points
```

This edge is only a starting point. Any real trading decision should also account for:

- bid/ask spread
- liquidity
- slippage
- fees or transaction costs
- market resolution rules
- whether the Polymarket bucket exactly matches the HKO resolution source

## Current Status

The current forecast archive covers only about 7 months of historical forecast snapshots. This is useful for prototyping, feature analysis, and backtesting workflow design, but it is not enough to trust for reliable real-money betting across the full year.

More historical forecast data should be added before relying on the model for serious trading decisions.

## Future Implementation Notes

Later implementation should add:

- training commands
- prediction commands
- backtest results
- model evaluation metrics
- expected value calculation against live or captured Polymarket prices

The first production-minded model should focus on calibrated probabilities, not only point temperature prediction.
