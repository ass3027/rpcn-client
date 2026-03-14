"""Run the Tekken Tag Tournament 2 API server.

Usage:
    python -m tekken_tt2
    python -m tekken_tt2 --host 0.0.0.0 --port 8000 --reload
"""
import argparse

import uvicorn


def main():
	parser = argparse.ArgumentParser(description="TTT2 RPCN API server")
	parser.add_argument("--host", default="0.0.0.0")
	parser.add_argument("--port", type=int, default=8000)
	parser.add_argument("--reload", action="store_true")
	args = parser.parse_args()
	uvicorn.run("tekken_tt2.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
	main()
