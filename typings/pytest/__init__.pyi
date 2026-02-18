from typing import Any, Callable, Pattern, Sequence, Type

class RaisesContext:
    def __enter__(self) -> BaseException: ...
    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool | None: ...

class _RaisesExc:
    def __call__(
        self,
        expected_exception: Type[BaseException] | tuple[Type[BaseException], ...],
        *,
        match: str | Pattern[str] | None = ...,
    ) -> RaisesContext: ...

class MonkeyPatch:
    def setenv(self, name: str, value: str, prepend: str | None = ...) -> None: ...
    def delenv(self, name: str, raising: bool = ...) -> None: ...
    def setattr(
        self, target: Any, name: str | None = ..., value: Any = ..., raising: bool = ...
    ) -> None: ...
    def chdir(self, path: Any) -> None: ...

def fixture(
    func: Callable[..., Any] | None = ...,
    *,
    scope: str = ...,
    params: Any = ...,
    autouse: bool = ...,
    ids: Any = ...,
    name: str | None = ...,
) -> Any: ...

class _MarkDecorator:
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...

class _Mark:
    def __getattr__(self, name: str) -> _MarkDecorator: ...
    def parametrize(
        self,
        argnames: str | Sequence[str],
        argvalues: Any,
        indirect: bool | list[str] = ...,
        ids: Any = ...,
        scope: str | None = ...,
    ) -> _MarkDecorator: ...

mark: _Mark

raises: _RaisesExc

def skip(reason: str = ...) -> None: ...
