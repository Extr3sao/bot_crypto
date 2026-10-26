from __future__ import annotations

__all__ = ["AdmissionController", "AdmissionResult", "AdmissionState"]


class AdmissionState:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return f"AdmissionState({self.__dict__})"


class AdmissionResult:
    def __init__(self, verdict, reason_codes=None, evidence=None, notes=None):
        self.verdict = verdict
        self.reason_codes = reason_codes or []
        self.evidence = evidence or {}
        self.notes = notes or ""

    def __repr__(self):
        return f"AdmissionResult(verdict={self.verdict!r})"


class AdmissionController:
    def __init__(self, **kwargs):
        self._state = AdmissionState(**kwargs)

    def admit(self, candidate):
        return AdmissionResult(verdict="NO_ADMISSION", reason_codes=["LOCAL_RECOVERY_UNSUPPORTED"])
