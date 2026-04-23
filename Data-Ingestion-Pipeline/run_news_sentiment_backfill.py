"""
run_news_sentiment_backfill.py

Compatibility wrapper for the news sentiment backfill pipeline.
The package-native implementation lives in `pipelines.news_sentiment_backfill`.
"""

from pipelines import news_sentiment_backfill as _impl

backfill_news_sentiment = _impl.backfill_news_sentiment
main = _impl.main


if __name__ == "__main__":
    args = _impl._parse_args()
    main(ticker=args.ticker, limit=args.limit)
