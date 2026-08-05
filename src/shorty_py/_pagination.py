"""Cursor pagination.

A :class:`Page` is one server page **plus** a bound fetcher for the next one, so
iterating reuses the original query params and only advances the opaque
``cursor``. That matters: server-side the cursor is *filter-bound*, and reusing
it against a different filter is rejected — so the SDK never mutates the other
params while walking.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from typing import Generic, TypeVar

T = TypeVar("T")

__all__ = ["AsyncPage", "Page"]


class Page(Generic[T]):
    """One page of a cursor-paginated collection (sync client).

    ``for row in page`` walks **this page only**;
    ``for row in page.auto_paging_iter()`` walks **every** following page.
    """

    __slots__ = ("_fetch_next", "data", "has_more", "next_cursor")

    def __init__(
        self,
        *,
        data: Sequence[T],
        has_more: bool,
        next_cursor: str | None,
        fetch_next: Callable[[str], Page[T]],
    ):
        #: The rows on this page.
        self.data: Sequence[T] = data
        #: Whether another page exists after this one.
        self.has_more = has_more
        #: Opaque cursor for the next page, or ``None`` on the last page.
        self.next_cursor = next_cursor
        self._fetch_next = fetch_next

    def __iter__(self) -> Iterator[T]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __bool__(self) -> bool:
        """A page is truthy when it has rows — so ``while page:`` terminates."""
        return len(self.data) > 0

    def __repr__(self) -> str:
        return f"Page(rows={len(self.data)}, has_more={self.has_more})"

    def next_page(self) -> Page[T] | None:
        """Fetch the next page, or ``None`` if this is the last one."""
        if not self.has_more or self.next_cursor is None:
            return None
        return self._fetch_next(self.next_cursor)

    def auto_paging_iter(self) -> Iterator[T]:
        """Yield every row across this page and all following pages, in order."""
        page: Page[T] | None = self
        while page is not None:
            yield from page.data
            page = page.next_page()


class AsyncPage(Generic[T]):
    """One page of a cursor-paginated collection (async client).

    ``async for row in page`` walks **every** row across all following pages —
    the async mirror of :meth:`Page.auto_paging_iter`, since an async client has
    no cheap way to offer both spellings.
    """

    __slots__ = ("_fetch_next", "data", "has_more", "next_cursor")

    def __init__(
        self,
        *,
        data: Sequence[T],
        has_more: bool,
        next_cursor: str | None,
        fetch_next: Callable[[str], Awaitable[AsyncPage[T]]],
    ):
        self.data: Sequence[T] = data
        self.has_more = has_more
        self.next_cursor = next_cursor
        self._fetch_next = fetch_next

    def __len__(self) -> int:
        return len(self.data)

    def __bool__(self) -> bool:
        return len(self.data) > 0

    def __repr__(self) -> str:
        return f"AsyncPage(rows={len(self.data)}, has_more={self.has_more})"

    async def next_page(self) -> AsyncPage[T] | None:
        """Fetch the next page, or ``None`` if this is the last one."""
        if not self.has_more or self.next_cursor is None:
            return None
        return await self._fetch_next(self.next_cursor)

    async def __aiter__(self) -> AsyncIterator[T]:
        page: AsyncPage[T] | None = self
        while page is not None:
            for row in page.data:
                yield row
            page = await page.next_page()

    def auto_paging_iter(self) -> AsyncIterator[T]:
        """Alias of ``__aiter__`` — parity with the sync spelling."""
        return self.__aiter__()
