"""Focused implementation modules behind the public pipeline runner facade.

`repograph.pipeline.runner` remains the stable import surface used by CLI,
services, and tests. The actual orchestration logic lives here so each major
runner concern has one clear home instead of growing back into a god-module.
"""

