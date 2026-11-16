def described_to_the_model(description: str):
    def describe[T: type](cls: T) -> T:
        cls.__doc__ = description
        return cls

    return describe
