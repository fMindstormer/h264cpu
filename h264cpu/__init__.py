"""h264cpu: standard H.264 videos whose decoder computes the pictures.

A program is a set of fields (boards of cells in regions of the frame) and one op per field; every op
is one H.264 explicit weighted prediction. The machine lays the program out, writes the stream, and
simulates what any conforming decoder must output, sample for sample.
"""
__version__ = "1.0.0"
