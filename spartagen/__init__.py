"""SpartaGen — a Sparta Remix generator built on real sample cutting.

Everything audible in a remix comes from the source video (or from a Sparta
base the user supplies): the engine cuts the source into pitch samples,
percussion hits and quotes, tunes the pitch samples to D, sequences them with
the pitch patterns documented on the Sparta Remix Wiki, polishes the result
with an Xleth-style FX chain and renders a synced video with ffmpeg.
"""

__version__ = "1.0.0rc1"

SAMPLE_RATE = 44100
