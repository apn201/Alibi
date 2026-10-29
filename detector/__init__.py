"""The demo AIS anomaly detector: a stand-in for "your existing AIS system".

It builds replay cases from recorded tracks (cases.py), runs the shared rules (../rules) over them,
sends each candidate to ALIBI over HTTP and nothing else (replay.py), and serves the GUI plus the
case files (serve.py). It never imports from `alibi/`: the HTTP boundary is the product's boundary.
"""
