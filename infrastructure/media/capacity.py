"""Existing process-local image capacity; no distributed quota is implied."""
from threading import BoundedSemaphore

image_gate = BoundedSemaphore(1)
