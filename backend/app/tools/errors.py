class ToolLookupError(LookupError):
    pass


class UpgradeNotEligibleError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
