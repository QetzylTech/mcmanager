"""Fake Minecraft server binary + in-process adapter double (Doc 13 section 6).

- ``fake_server.py`` — a real subprocess binary run by the native-adapter
  conformance tests and the E2E suite.
- ``fake_adapter.py`` — an in-process ``ProcessControlPort`` double driven by
  the **same argv** convention as ``fake_server.py``, so the C1–C14
  conformance suite runs identical scenarios against fake and native adapters.

Neither is ever imported by ``app/``.
"""
