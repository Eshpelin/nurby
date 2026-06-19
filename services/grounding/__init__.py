"""FindAnything / visual grounding (LocateAnything).

A single HTTP seam (``GroundingClient``) fronts an open-vocabulary
visual-grounding model. The model may run in the bundled local GPU
microservice (``server.py``) or behind a remote endpoint; Nurby code only
ever speaks HTTP to it, so the GPU never has to be present in CI. See
docs/findanything-design.md.
"""
