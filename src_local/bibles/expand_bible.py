"""Expand the bible with hand-written CS fundamentals, algorithm patterns,
design patterns, and problem-solving strategies.

Run once:  python -m src_local.bibles.expand_bible
Appends new entries to coding.bible.json and reasoning.bible.json,
then rebuilds both index files.
"""

from __future__ import annotations

import json
from pathlib import Path

BIBLES_DIR = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════════════
# NEW CODING BIBLE ENTRIES
# Topics: decorators, context managers, concurrency, data structures,
#         algorithms, design patterns, error handling
# ═══════════════════════════════════════════════════════════════════════

NEW_CODING: list[dict] = [
    # ── Decorators ──────────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0000",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:decorator", "topic:functools", "topic:wraps"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/decorators.md",
        "heading_path": ["Python Patterns", "Decorators", "Basic Decorator with functools.wraps"],
        "text": (
            "A decorator wraps a function to add behavior. Always use "
            "@functools.wraps(func) to preserve the original function's "
            "__name__, __doc__, and __module__.\n\n"
            "```python\n"
            "import functools\n\n"
            "def my_decorator(func):\n"
            "    @functools.wraps(func)\n"
            "    def wrapper(*args, **kwargs):\n"
            "        print(f'Calling {func.__name__}')\n"
            "        result = func(*args, **kwargs)\n"
            "        print(f'{func.__name__} returned {result}')\n"
            "        return result\n"
            "    return wrapper\n"
            "```\n\n"
            "For decorators that accept arguments, add an outer factory function:\n"
            "```python\n"
            "def repeat(n=2):\n"
            "    def decorator(func):\n"
            "        @functools.wraps(func)\n"
            "        def wrapper(*args, **kwargs):\n"
            "            for _ in range(n):\n"
            "                result = func(*args, **kwargs)\n"
            "            return result\n"
            "        return wrapper\n"
            "    return decorator\n"
            "```"
        ),
    },
    {
        "id": "coding:cs-patterns:0001",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:decorator", "topic:async", "topic:sync", "topic:inspect"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/decorators.md",
        "heading_path": ["Python Patterns", "Decorators", "Decorator Supporting Both Sync and Async"],
        "text": (
            "To write a decorator that works on both sync and async functions, "
            "use inspect.iscoroutinefunction() to detect the function type and "
            "create the appropriate wrapper:\n\n"
            "```python\n"
            "import asyncio\n"
            "import functools\n"
            "import inspect\n\n"
            "def retry(max_retries=3, base_delay=1.0, exceptions=(Exception,)):\n"
            "    def decorator(func):\n"
            "        if inspect.iscoroutinefunction(func):\n"
            "            @functools.wraps(func)\n"
            "            async def async_wrapper(*args, **kwargs):\n"
            "                for attempt in range(max_retries + 1):\n"
            "                    try:\n"
            "                        return await func(*args, **kwargs)\n"
            "                    except exceptions as e:\n"
            "                        if attempt == max_retries:\n"
            "                            raise\n"
            "                        delay = base_delay * (2 ** attempt)\n"
            "                        await asyncio.sleep(delay)\n"
            "            return async_wrapper\n"
            "        else:\n"
            "            @functools.wraps(func)\n"
            "            def sync_wrapper(*args, **kwargs):\n"
            "                import time\n"
            "                for attempt in range(max_retries + 1):\n"
            "                    try:\n"
            "                        return func(*args, **kwargs)\n"
            "                    except exceptions as e:\n"
            "                        if attempt == max_retries:\n"
            "                            raise\n"
            "                        delay = base_delay * (2 ** attempt)\n"
            "                        time.sleep(delay)\n"
            "            return sync_wrapper\n"
            "    return decorator\n"
            "```\n\n"
            "Key: inspect.iscoroutinefunction() must be checked at decoration "
            "time (when the decorator runs), not at call time."
        ),
    },
    # ── Context Managers ────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0002",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:context", "topic:manager", "topic:timer", "topic:perf_counter"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/context_managers.md",
        "heading_path": ["Python Patterns", "Context Managers", "Timer Context Manager"],
        "text": (
            "A context manager that measures execution time. Use "
            "time.perf_counter() for precision (not time.time()):\n\n"
            "```python\n"
            "import time\n\n"
            "class Timer:\n"
            "    def __enter__(self):\n"
            "        self.start = time.perf_counter()\n"
            "        return self\n\n"
            "    def __exit__(self, exc_type, exc_val, exc_tb):\n"
            "        self.elapsed = time.perf_counter() - self.start\n"
            "        self.elapsed_ms = self.elapsed * 1000\n"
            "        print(f'Elapsed: {self.elapsed_ms:.2f} ms')\n"
            "        return False  # Don't suppress exceptions\n"
            "```\n\n"
            "Usage: `with Timer() as t: ...`\n"
            "After the block, t.elapsed_ms holds the measurement.\n\n"
            "Alternative using contextlib:\n"
            "```python\n"
            "from contextlib import contextmanager\n\n"
            "@contextmanager\n"
            "def timer():\n"
            "    start = time.perf_counter()\n"
            "    yield\n"
            "    elapsed = (time.perf_counter() - start) * 1000\n"
            "    print(f'Elapsed: {elapsed:.2f} ms')\n"
            "```"
        ),
    },
    # ── Concurrency Patterns ────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0003",
        "tags": ["src:cs-patterns", "cat:concurrency", "topic:asyncio", "topic:gather", "topic:error", "topic:subscriber", "topic:event"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/concurrency.md",
        "heading_path": ["Python Patterns", "Concurrency", "Per-Task Error Handling with asyncio.gather"],
        "text": (
            "When using asyncio.gather() with multiple coroutines where one "
            "failure should not crash the others, wrap EACH coroutine "
            "individually — do NOT wrap the entire gather in a single try/except.\n\n"
            "WRONG — one failure kills all:\n"
            "```python\n"
            "try:\n"
            "    await asyncio.gather(*tasks)\n"
            "except Exception as e:\n"
            "    print(f'Error: {e}')  # Only catches first failure\n"
            "```\n\n"
            "RIGHT — per-task isolation:\n"
            "```python\n"
            "async def safe_call(coro, name='task'):\n"
            "    try:\n"
            "        return await coro\n"
            "    except Exception as e:\n"
            "        print(f'Error in {name}: {e}')\n"
            "        return None\n\n"
            "results = await asyncio.gather(\n"
            "    *[safe_call(cb(*args), name=cb.__name__) for cb in callbacks]\n"
            ")\n"
            "```\n\n"
            "Or use return_exceptions=True:\n"
            "```python\n"
            "results = await asyncio.gather(*tasks, return_exceptions=True)\n"
            "for r in results:\n"
            "    if isinstance(r, Exception):\n"
            "        print(f'Task failed: {r}')\n"
            "```"
        ),
    },
    {
        "id": "coding:cs-patterns:0004",
        "tags": ["src:cs-patterns", "cat:concurrency", "topic:event", "topic:bus", "topic:pubsub", "topic:asyncio", "topic:subscribe"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/concurrency.md",
        "heading_path": ["Python Patterns", "Concurrency", "AsyncEventBus Implementation"],
        "text": (
            "A proper async event bus with per-subscriber error isolation:\n\n"
            "```python\n"
            "import asyncio\n"
            "import logging\n\n"
            "logger = logging.getLogger(__name__)\n\n"
            "class AsyncEventBus:\n"
            "    def __init__(self):\n"
            "        self._subscribers: dict[str, list[callable]] = {}\n\n"
            "    def subscribe(self, event: str, callback: callable) -> None:\n"
            "        self._subscribers.setdefault(event, []).append(callback)\n\n"
            "    def unsubscribe(self, event: str, callback: callable) -> None:\n"
            "        if event in self._subscribers:\n"
            "            self._subscribers[event] = [\n"
            "                cb for cb in self._subscribers[event] if cb is not callback\n"
            "            ]\n\n"
            "    async def publish(self, event: str, *args, **kwargs) -> None:\n"
            "        subscribers = self._subscribers.get(event, [])\n"
            "        if not subscribers:\n"
            "            return\n"
            "        # Wrap each subscriber so one failure doesn't crash others\n"
            "        async def _safe(cb):\n"
            "            try:\n"
            "                await cb(*args, **kwargs)\n"
            "            except Exception:\n"
            "                logger.exception('Subscriber %s failed for %s', cb.__name__, event)\n"
            "        await asyncio.gather(*[_safe(cb) for cb in subscribers])\n"
            "```\n\n"
            "Key design points:\n"
            "- subscribe/unsubscribe are sync (no IO needed)\n"
            "- publish is async (runs callbacks concurrently)\n"
            "- Each callback wrapped in _safe() for error isolation\n"
            "- Filter-style removal in unsubscribe avoids ValueError if missing"
        ),
    },
    {
        "id": "coding:cs-patterns:0005",
        "tags": ["src:cs-patterns", "cat:concurrency", "topic:rate", "topic:limiter", "topic:token", "topic:bucket", "topic:threading", "topic:lock"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/concurrency.md",
        "heading_path": ["Python Patterns", "Concurrency", "Token Bucket Rate Limiter"],
        "text": (
            "The token bucket algorithm controls throughput. Tokens accumulate "
            "over time up to a burst limit. Each operation consumes one token.\n\n"
            "```python\n"
            "import time\n"
            "import threading\n\n"
            "class RateLimiter:\n"
            "    def __init__(self, rate: float = 10.0, burst: int = 10):\n"
            "        self.rate = rate      # tokens per second\n"
            "        self.burst = burst    # max tokens\n"
            "        self._tokens = float(burst)\n"
            "        self._last_refill = time.monotonic()\n"
            "        self._lock = threading.Lock()\n\n"
            "    def _refill(self) -> None:\n"
            "        now = time.monotonic()\n"
            "        elapsed = now - self._last_refill\n"
            "        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)\n"
            "        self._last_refill = now\n\n"
            "    def try_acquire(self) -> bool:\n"
            "        with self._lock:\n"
            "            self._refill()\n"
            "            if self._tokens >= 1:\n"
            "                self._tokens -= 1\n"
            "                return True\n"
            "            return False\n\n"
            "    def acquire(self) -> None:\n"
            "        while True:\n"
            "            with self._lock:\n"
            "                self._refill()\n"
            "                if self._tokens >= 1:\n"
            "                    self._tokens -= 1\n"
            "                    return\n"
            "            # IMPORTANT: sleep OUTSIDE the lock so other threads\n"
            "            # can acquire tokens while we wait\n"
            "            time.sleep(1.0 / self.rate)\n"
            "```\n\n"
            "Critical: the lock must be RELEASED during sleep() in acquire(). "
            "Holding the lock while sleeping blocks all other threads."
        ),
    },
    # ── Data Structures ─────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0006",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:linked", "topic:list", "topic:node", "topic:data", "topic:structure"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/data_structures.md",
        "heading_path": ["Data Structures", "Linked List"],
        "text": (
            "Singly linked list implementation in Python:\n\n"
            "```python\n"
            "class Node:\n"
            "    __slots__ = ('value', 'next')\n"
            "    def __init__(self, value, next=None):\n"
            "        self.value = value\n"
            "        self.next = next\n\n"
            "class LinkedList:\n"
            "    def __init__(self):\n"
            "        self.head = None\n"
            "        self._size = 0\n\n"
            "    def prepend(self, value):\n"
            "        self.head = Node(value, self.head)\n"
            "        self._size += 1\n\n"
            "    def append(self, value):\n"
            "        if not self.head:\n"
            "            self.head = Node(value)\n"
            "        else:\n"
            "            current = self.head\n"
            "            while current.next:\n"
            "                current = current.next\n"
            "            current.next = Node(value)\n"
            "        self._size += 1\n\n"
            "    def remove(self, value):\n"
            "        if not self.head:\n"
            "            return\n"
            "        if self.head.value == value:\n"
            "            self.head = self.head.next\n"
            "            self._size -= 1\n"
            "            return\n"
            "        current = self.head\n"
            "        while current.next:\n"
            "            if current.next.value == value:\n"
            "                current.next = current.next.next\n"
            "                self._size -= 1\n"
            "                return\n"
            "            current = current.next\n\n"
            "    def __len__(self):\n"
            "        return self._size\n\n"
            "    def __iter__(self):\n"
            "        current = self.head\n"
            "        while current:\n"
            "            yield current.value\n"
            "            current = current.next\n"
            "```"
        ),
    },
    {
        "id": "coding:cs-patterns:0007",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:binary", "topic:search", "topic:tree", "topic:bst"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/data_structures.md",
        "heading_path": ["Data Structures", "Binary Search Tree"],
        "text": (
            "Binary search tree with insert, search, and in-order traversal:\n\n"
            "```python\n"
            "class BSTNode:\n"
            "    __slots__ = ('value', 'left', 'right')\n"
            "    def __init__(self, value):\n"
            "        self.value = value\n"
            "        self.left = None\n"
            "        self.right = None\n\n"
            "class BST:\n"
            "    def __init__(self):\n"
            "        self.root = None\n\n"
            "    def insert(self, value):\n"
            "        if not self.root:\n"
            "            self.root = BSTNode(value)\n"
            "            return\n"
            "        node = self.root\n"
            "        while True:\n"
            "            if value < node.value:\n"
            "                if node.left is None:\n"
            "                    node.left = BSTNode(value)\n"
            "                    return\n"
            "                node = node.left\n"
            "            else:\n"
            "                if node.right is None:\n"
            "                    node.right = BSTNode(value)\n"
            "                    return\n"
            "                node = node.right\n\n"
            "    def search(self, value) -> bool:\n"
            "        node = self.root\n"
            "        while node:\n"
            "            if value == node.value:\n"
            "                return True\n"
            "            elif value < node.value:\n"
            "                node = node.left\n"
            "            else:\n"
            "                node = node.right\n"
            "        return False\n\n"
            "    def inorder(self):\n"
            "        def _walk(node):\n"
            "            if node:\n"
            "                yield from _walk(node.left)\n"
            "                yield node.value\n"
            "                yield from _walk(node.right)\n"
            "        return list(_walk(self.root))\n"
            "```\n\n"
            "Complexity: O(log n) average for insert/search, O(n) worst case "
            "(degenerate/unbalanced tree)."
        ),
    },
    {
        "id": "coding:cs-patterns:0008",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:graph", "topic:bfs", "topic:dfs", "topic:traversal", "topic:adjacency"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/data_structures.md",
        "heading_path": ["Data Structures", "Graph", "BFS and DFS"],
        "text": (
            "Graph traversal using adjacency list representation:\n\n"
            "```python\n"
            "from collections import deque\n\n"
            "class Graph:\n"
            "    def __init__(self):\n"
            "        self.adj: dict[str, list[str]] = {}\n\n"
            "    def add_edge(self, u, v, directed=False):\n"
            "        self.adj.setdefault(u, []).append(v)\n"
            "        if not directed:\n"
            "            self.adj.setdefault(v, []).append(u)\n\n"
            "    def bfs(self, start):\n"
            "        visited = {start}\n"
            "        queue = deque([start])\n"
            "        order = []\n"
            "        while queue:\n"
            "            node = queue.popleft()\n"
            "            order.append(node)\n"
            "            for neighbor in self.adj.get(node, []):\n"
            "                if neighbor not in visited:\n"
            "                    visited.add(neighbor)\n"
            "                    queue.append(neighbor)\n"
            "        return order\n\n"
            "    def dfs(self, start):\n"
            "        visited = set()\n"
            "        order = []\n"
            "        def _visit(node):\n"
            "            visited.add(node)\n"
            "            order.append(node)\n"
            "            for neighbor in self.adj.get(node, []):\n"
            "                if neighbor not in visited:\n"
            "                    _visit(neighbor)\n"
            "        _visit(start)\n"
            "        return order\n"
            "```\n\n"
            "BFS uses a queue (FIFO) — finds shortest paths in unweighted graphs.\n"
            "DFS uses recursion/stack (LIFO) — useful for cycle detection, "
            "topological sort, connected components."
        ),
    },
    {
        "id": "coding:cs-patterns:0009",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:heap", "topic:priority", "topic:queue", "topic:heapq"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/data_structures.md",
        "heading_path": ["Data Structures", "Heap / Priority Queue"],
        "text": (
            "Python's heapq module implements a min-heap. For a priority queue:\n\n"
            "```python\n"
            "import heapq\n\n"
            "class PriorityQueue:\n"
            "    def __init__(self):\n"
            "        self._heap = []\n"
            "        self._counter = 0  # tiebreaker for equal priorities\n\n"
            "    def push(self, item, priority=0):\n"
            "        heapq.heappush(self._heap, (priority, self._counter, item))\n"
            "        self._counter += 1\n\n"
            "    def pop(self):\n"
            "        if not self._heap:\n"
            "            raise IndexError('empty queue')\n"
            "        priority, _, item = heapq.heappop(self._heap)\n"
            "        return item\n\n"
            "    def peek(self):\n"
            "        if not self._heap:\n"
            "            raise IndexError('empty queue')\n"
            "        return self._heap[0][2]\n\n"
            "    def __len__(self):\n"
            "        return len(self._heap)\n\n"
            "    def __bool__(self):\n"
            "        return bool(self._heap)\n"
            "```\n\n"
            "The counter field breaks ties when priorities are equal, ensuring "
            "FIFO order for same-priority items. Without it, heapq would try "
            "to compare the items directly (fails if items aren't comparable)."
        ),
    },
    # ── Algorithms ──────────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0010",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:sort", "topic:sorting", "topic:merge", "topic:quick", "topic:complexity"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/algorithms.md",
        "heading_path": ["Algorithms", "Sorting", "Merge Sort and Quick Sort"],
        "text": (
            "Merge Sort — stable, O(n log n) guaranteed:\n"
            "```python\n"
            "def merge_sort(arr):\n"
            "    if len(arr) <= 1:\n"
            "        return arr\n"
            "    mid = len(arr) // 2\n"
            "    left = merge_sort(arr[:mid])\n"
            "    right = merge_sort(arr[mid:])\n"
            "    return merge(left, right)\n\n"
            "def merge(left, right):\n"
            "    result = []\n"
            "    i = j = 0\n"
            "    while i < len(left) and j < len(right):\n"
            "        if left[i] <= right[j]:\n"
            "            result.append(left[i]); i += 1\n"
            "        else:\n"
            "            result.append(right[j]); j += 1\n"
            "    result.extend(left[i:])\n"
            "    result.extend(right[j:])\n"
            "    return result\n"
            "```\n\n"
            "Quick Sort — O(n log n) average, O(n²) worst case:\n"
            "```python\n"
            "def quick_sort(arr):\n"
            "    if len(arr) <= 1:\n"
            "        return arr\n"
            "    pivot = arr[len(arr) // 2]\n"
            "    left = [x for x in arr if x < pivot]\n"
            "    middle = [x for x in arr if x == pivot]\n"
            "    right = [x for x in arr if x > pivot]\n"
            "    return quick_sort(left) + middle + quick_sort(right)\n"
            "```\n\n"
            "Use Python's built-in sorted() (Timsort, O(n log n)) in production. "
            "Implement these to understand the algorithms."
        ),
    },
    {
        "id": "coding:cs-patterns:0011",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:binary", "topic:search", "topic:bisect"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/algorithms.md",
        "heading_path": ["Algorithms", "Binary Search"],
        "text": (
            "Binary search on a sorted array — O(log n):\n\n"
            "```python\n"
            "def binary_search(arr, target):\n"
            "    lo, hi = 0, len(arr) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if arr[mid] == target:\n"
            "            return mid\n"
            "        elif arr[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1  # not found\n"
            "```\n\n"
            "Python stdlib: use bisect module for production code:\n"
            "```python\n"
            "import bisect\n"
            "# Find insertion point (left)\n"
            "idx = bisect.bisect_left(sorted_list, target)\n"
            "# Check if target exists\n"
            "found = idx < len(sorted_list) and sorted_list[idx] == target\n"
            "# Insert maintaining sort order\n"
            "bisect.insort(sorted_list, new_value)\n"
            "```\n\n"
            "Common variations:\n"
            "- bisect_left: leftmost insertion point (first occurrence)\n"
            "- bisect_right: rightmost insertion point (after last occurrence)\n"
            "- Predicate search: find first True in [F,F,F,...,T,T,T]"
        ),
    },
    {
        "id": "coding:cs-patterns:0012",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:recursion", "topic:dynamic", "topic:programming", "topic:memoize"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/algorithms.md",
        "heading_path": ["Algorithms", "Recursion and Dynamic Programming"],
        "text": (
            "Recursion pattern with memoization (top-down DP):\n\n"
            "```python\n"
            "from functools import lru_cache\n\n"
            "# Fibonacci — naive O(2^n) vs memoized O(n)\n"
            "@lru_cache(maxsize=None)\n"
            "def fib(n):\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    return fib(n - 1) + fib(n - 2)\n"
            "```\n\n"
            "Bottom-up DP (iterative, no recursion depth limit):\n"
            "```python\n"
            "def fib_dp(n):\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    prev, curr = 0, 1\n"
            "    for _ in range(2, n + 1):\n"
            "        prev, curr = curr, prev + curr\n"
            "    return curr\n"
            "```\n\n"
            "DP recipe:\n"
            "1. Define subproblem: what does dp[i] represent?\n"
            "2. Find recurrence: dp[i] = f(dp[i-1], dp[i-2], ...)\n"
            "3. Identify base cases: dp[0] = ?, dp[1] = ?\n"
            "4. Determine iteration order: forward or backward?\n"
            "5. Optimize space if only last few values needed"
        ),
    },
    # ── Complexity Analysis ─────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0013",
        "tags": ["src:cs-patterns", "cat:algorithms", "topic:complexity", "topic:big", "topic:time", "topic:space"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/algorithms.md",
        "heading_path": ["Algorithms", "Complexity Analysis", "Big-O Reference"],
        "text": (
            "Common time complexities (fastest to slowest):\n\n"
            "O(1)       — constant: hash lookup, array index\n"
            "O(log n)   — logarithmic: binary search, balanced BST\n"
            "O(n)       — linear: array scan, linked list traversal\n"
            "O(n log n) — linearithmic: merge sort, heap sort, Timsort\n"
            "O(n²)      — quadratic: nested loops, bubble sort\n"
            "O(2^n)     — exponential: naive recursion, power set\n"
            "O(n!)      — factorial: permutations, brute-force TSP\n\n"
            "Python operation complexities:\n"
            "- list.append(): O(1) amortized\n"
            "- list[i]: O(1)\n"
            "- list.insert(0, x): O(n)\n"
            "- x in list: O(n)\n"
            "- x in set: O(1) average\n"
            "- dict[key]: O(1) average\n"
            "- sorted(): O(n log n)\n"
            "- deque.appendleft(): O(1)\n"
            "- heapq.heappush(): O(log n)\n\n"
            "Rule of thumb for interview constraints:\n"
            "- n ≤ 20: O(2^n) or O(n!) OK\n"
            "- n ≤ 1000: O(n²) OK\n"
            "- n ≤ 10^6: need O(n log n) or O(n)\n"
            "- n ≤ 10^9: need O(log n) or O(1)"
        ),
    },
    # ── Design Patterns ─────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0014",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:observer", "topic:pattern", "topic:design", "topic:callback"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/design_patterns.md",
        "heading_path": ["Design Patterns", "Observer Pattern"],
        "text": (
            "Observer pattern — decouple event producers from consumers:\n\n"
            "```python\n"
            "class EventEmitter:\n"
            "    def __init__(self):\n"
            "        self._listeners: dict[str, list[callable]] = {}\n\n"
            "    def on(self, event: str, callback: callable) -> None:\n"
            "        self._listeners.setdefault(event, []).append(callback)\n\n"
            "    def off(self, event: str, callback: callable) -> None:\n"
            "        if event in self._listeners:\n"
            "            self._listeners[event] = [\n"
            "                cb for cb in self._listeners[event] if cb is not callback\n"
            "            ]\n\n"
            "    def emit(self, event: str, *args, **kwargs) -> None:\n"
            "        for callback in self._listeners.get(event, []):\n"
            "            callback(*args, **kwargs)\n"
            "```\n\n"
            "Key principles:\n"
            "- Use 'is not' comparison for removal (identity, not equality)\n"
            "- Filter-style removal avoids ValueError if callback already removed\n"
            "- setdefault() avoids KeyError on first subscription\n"
            "- Producer knows nothing about consumer implementations"
        ),
    },
    {
        "id": "coding:cs-patterns:0015",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:lru", "topic:cache", "topic:ordered", "topic:dict"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/design_patterns.md",
        "heading_path": ["Design Patterns", "LRU Cache from Scratch"],
        "text": (
            "LRU (Least Recently Used) cache using OrderedDict:\n\n"
            "```python\n"
            "from collections import OrderedDict\n\n"
            "class LRUCache:\n"
            "    def __init__(self, capacity: int):\n"
            "        self.capacity = capacity\n"
            "        self._cache = OrderedDict()\n\n"
            "    def get(self, key):\n"
            "        if key not in self._cache:\n"
            "            return None\n"
            "        self._cache.move_to_end(key)  # mark as recently used\n"
            "        return self._cache[key]\n\n"
            "    def put(self, key, value):\n"
            "        if key in self._cache:\n"
            "            self._cache.move_to_end(key)\n"
            "        self._cache[key] = value\n"
            "        if len(self._cache) > self.capacity:\n"
            "            self._cache.popitem(last=False)  # evict oldest\n\n"
            "    def __len__(self):\n"
            "        return len(self._cache)\n"
            "```\n\n"
            "For production, use @functools.lru_cache(maxsize=N) instead.\n"
            "For thread-safe version, wrap get/put in threading.Lock."
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════
# NEW REASONING BIBLE ENTRIES
# Topics: problem-solving strategies, binary encoding, logic puzzles,
#         debugging methodology, design tradeoffs, complexity reasoning
# ═══════════════════════════════════════════════════════════════════════

NEW_REASONING: list[dict] = [
    # ── Problem Solving Strategies ──────────────────────────────────
    {
        "id": "reasoning:problem-solving:0000",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:binary", "topic:encoding", "topic:information", "topic:theory"],
        "source_id": "problem-solving",
        "source_path": "hand-written/problem_solving.md",
        "heading_path": ["Problem Solving", "Binary Encoding Strategy"],
        "text": (
            "Binary encoding uses bits to represent choices. With N bits, "
            "you can represent 2^N distinct values.\n\n"
            "Classic application — identifying 1 poisoned bottle among 1000:\n"
            "- 10 prisoners = 10 bits = 2^10 = 1024 combinations (> 1000)\n"
            "- Number each bottle 1–1000\n"
            "- Convert each number to 10-bit binary\n"
            "- Prisoner K drinks from every bottle where bit K is 1\n"
            "- After 24 hours, read which prisoners died\n"
            "- Dead prisoners = 1 bits → binary number = poisoned bottle\n\n"
            "Example: bottle 730\n"
            "- 730 in binary: 1011011010 (512+128+64+16+8+2)\n"
            "- Bits set at positions: 1, 3, 4, 6, 7, 9 (0-indexed from right)\n"
            "- Prisoners 1, 3, 4, 6, 7, 9 drink from bottle 730\n"
            "- If those prisoners die → 1011011010 → bottle 730\n\n"
            "Key insight: each prisoner is an independent binary digit. "
            "This is information-theoretically optimal — log₂(1000) ≈ 10 "
            "prisoners needed minimum."
        ),
    },
    {
        "id": "reasoning:problem-solving:0001",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:divide", "topic:conquer", "topic:balance", "topic:weighing"],
        "source_id": "problem-solving",
        "source_path": "hand-written/problem_solving.md",
        "heading_path": ["Problem Solving", "Balance Scale Problems"],
        "text": (
            "Balance scale problems: a scale has THREE outcomes per weighing "
            "(left heavy, balanced, right heavy), so each weighing gives "
            "log₃ information.\n\n"
            "With K weighings, you can distinguish 3^K states:\n"
            "- 1 weighing: 3 states\n"
            "- 2 weighings: 9 states\n"
            "- 3 weighings: 27 states\n\n"
            "12-ball problem (find odd ball + heavy/lighter in 3 weighings):\n"
            "- 12 balls × 2 directions = 24 possible states (< 27 = 3³) ✓\n\n"
            "Solution strategy:\n"
            "1. FIRST WEIGHING: 4 vs 4 (leave 4 aside)\n"
            "   - Balanced → odd ball is in the 4 set aside\n"
            "   - Tipped → odd ball is in the 8 on the scale, AND you now "
            "know which side was heavy\n\n"
            "2. SECOND WEIGHING: Use what you learned.\n"
            "   - If balanced first: weigh 3 of the 4 suspects vs 3 known-good\n"
            "     - Balanced → remaining 1 is odd (weigh vs known to find H/L)\n"
            "     - Tipped → odd is among those 3, and you know if H or L\n"
            "   - If tipped first: rearrange 8 suspects strategically\n"
            "     - Move some from heavy side to light side\n"
            "     - Replace some with known-good balls\n"
            "     - The scale's new behavior reveals which group has the odd ball\n\n"
            "3. THIRD WEIGHING: 1 vs 1 (or 1 vs known-good) to identify exact ball\n\n"
            "KEY INSIGHT: after each weighing, categorize balls as "
            "'possibly heavy', 'possibly light', or 'known good'. "
            "Never just divide randomly — use the information from prior weighings."
        ),
    },
    {
        "id": "reasoning:problem-solving:0002",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:water", "topic:jug", "topic:measure", "topic:gcd", "topic:logic"],
        "source_id": "problem-solving",
        "source_path": "hand-written/problem_solving.md",
        "heading_path": ["Problem Solving", "Water Jug Problems"],
        "text": (
            "Water jug problems: measure a target volume using jugs of "
            "known sizes with no markings.\n\n"
            "Key theorem: with jugs of size A and B, you can measure any "
            "volume that is a multiple of gcd(A, B), up to max(A, B).\n"
            "Example: 3-gallon and 5-gallon → gcd(3,5) = 1 → can measure "
            "any integer from 1 to 5.\n\n"
            "To measure 4 gallons with 3-gal and 5-gal jugs:\n"
            "1. Fill the 5-gal jug (5-gal: 5, 3-gal: 0)\n"
            "2. Pour 5→3 until 3 is full (5-gal: 2, 3-gal: 3)\n"
            "3. Empty the 3-gal jug (5-gal: 2, 3-gal: 0)\n"
            "4. Pour 5→3 (5-gal: 0, 3-gal: 2)\n"
            "5. Fill the 5-gal jug (5-gal: 5, 3-gal: 2)\n"
            "6. Pour 5→3 until 3 is full — only 1 gallon fits (5-gal: 4, 3-gal: 3)\n"
            "Result: 4 gallons in the 5-GALLON jug.\n\n"
            "IMPORTANT: Track which jug holds the result. A 3-gallon jug "
            "cannot hold 4 gallons — the result must be in the 5-gallon jug.\n"
            "Always state the container that holds the final answer."
        ),
    },
    # ── Debugging Methodology ───────────────────────────────────────
    {
        "id": "reasoning:problem-solving:0003",
        "tags": ["src:problem-solving", "cat:debugging", "topic:async", "topic:hang", "topic:deadlock", "topic:load", "topic:coroutine"],
        "source_id": "problem-solving",
        "source_path": "hand-written/debugging.md",
        "heading_path": ["Debugging", "Async Coroutine Hangs Under Load"],
        "text": (
            "When a coroutine hangs under load but works in isolation, "
            "investigate these root causes in order:\n\n"
            "1. SEMAPHORE / LOCK STARVATION\n"
            "   - Symptom: awaiting a lock/semaphore that's held by a task "
            "that's also waiting\n"
            "   - Diagnose: log lock acquire/release with task IDs. Check "
            "for nested lock acquisition (A holds lock1, waits lock2; "
            "B holds lock2, waits lock1)\n"
            "   - Fix: always acquire locks in consistent order; use "
            "asyncio.wait_for() with timeout; consider asyncio.Semaphore "
            "with bounded concurrency\n\n"
            "2. CONNECTION POOL EXHAUSTION\n"
            "   - Symptom: tasks block on db.acquire() or aiohttp session\n"
            "   - Diagnose: log pool size, active/idle counts; check if "
            "connections are being returned (missing 'async with')\n"
            "   - Fix: ensure 'async with pool.acquire() as conn'; increase "
            "pool size; add connection timeout\n\n"
            "3. EVENT LOOP BLOCKING\n"
            "   - Symptom: entire loop freezes, not just one task\n"
            "   - Diagnose: use loop.slow_callback_duration; search for "
            "sync IO (file reads, DNS) in async code\n"
            "   - Fix: run_in_executor() for sync IO; use aiofiles for "
            "file IO; asyncio.to_thread() in Python 3.9+\n\n"
            "4. UNBOUNDED TASK CREATION\n"
            "   - Symptom: memory grows, tasks pile up, system slows\n"
            "   - Diagnose: len(asyncio.all_tasks()); memory profiling\n"
            "   - Fix: asyncio.Semaphore to cap concurrency; task queue "
            "pattern; backpressure mechanism"
        ),
    },
    # ── Design Tradeoffs ────────────────────────────────────────────
    {
        "id": "reasoning:problem-solving:0004",
        "tags": ["src:problem-solving", "cat:design", "topic:composition", "topic:inheritance", "topic:tradeoff", "topic:pattern"],
        "source_id": "problem-solving",
        "source_path": "hand-written/design_tradeoffs.md",
        "heading_path": ["Design Tradeoffs", "Composition vs Inheritance"],
        "text": (
            "Prefer composition over inheritance in most cases.\n\n"
            "Use INHERITANCE when:\n"
            "- IS-A relationship is natural and stable (Dog is an Animal)\n"
            "- You need polymorphism through a type hierarchy\n"
            "- The base class is designed for extension (abstract methods)\n"
            "- Framework requires it (Django models, Textual widgets)\n\n"
            "Use COMPOSITION when:\n"
            "- HAS-A relationship (Car has an Engine, not Car is an Engine)\n"
            "- Behavior can change at runtime\n"
            "- Multiple unrelated behaviors need combining\n"
            "- You want to avoid the fragile base class problem\n\n"
            "Python-specific guidance:\n"
            "- Mixins are lightweight composition via multiple inheritance\n"
            "- Protocols (typing.Protocol) give duck-typing with type safety\n"
            "- dataclasses + composition often beats class hierarchies\n"
            "- If you find yourself overriding many parent methods, "
            "composition is probably better\n\n"
            "Red flags for inheritance:\n"
            "- Deep hierarchies (> 3 levels)\n"
            "- Inheriting to reuse code (not for polymorphism)\n"
            "- 'God class' base that does everything"
        ),
    },
    {
        "id": "reasoning:problem-solving:0005",
        "tags": ["src:problem-solving", "cat:design", "topic:sync", "topic:async", "topic:threading", "topic:concurrency", "topic:tradeoff"],
        "source_id": "problem-solving",
        "source_path": "hand-written/design_tradeoffs.md",
        "heading_path": ["Design Tradeoffs", "Sync vs Async vs Threading"],
        "text": (
            "Choosing the right concurrency model:\n\n"
            "SYNC (no concurrency):\n"
            "- CPU-bound work with no IO waits\n"
            "- Simple scripts, CLI tools\n"
            "- When code clarity matters more than throughput\n\n"
            "ASYNCIO:\n"
            "- IO-bound work: HTTP calls, database queries, file IO\n"
            "- Many concurrent connections (web servers, chat)\n"
            "- Single-threaded — no race conditions on shared state\n"
            "- Cannot parallelize CPU work (GIL still applies)\n\n"
            "THREADING:\n"
            "- IO-bound work with sync libraries that don't support async\n"
            "- GUI applications (keep UI responsive)\n"
            "- When you need shared memory between workers\n"
            "- Beware: race conditions, locks, deadlocks\n\n"
            "MULTIPROCESSING:\n"
            "- CPU-bound work: number crunching, image processing\n"
            "- True parallelism (bypasses GIL)\n"
            "- Higher memory cost (separate process per worker)\n"
            "- Use ProcessPoolExecutor for simple cases\n\n"
            "Rule of thumb:\n"
            "- IO-bound + modern code → asyncio\n"
            "- IO-bound + legacy sync libs → threading\n"
            "- CPU-bound → multiprocessing\n"
            "- Simple/small → just use sync"
        ),
    },
    # ── Logic and Math Reasoning ────────────────────────────────────
    {
        "id": "reasoning:problem-solving:0006",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:logic", "topic:reasoning", "topic:proof", "topic:elimination"],
        "source_id": "problem-solving",
        "source_path": "hand-written/logic.md",
        "heading_path": ["Logic", "Systematic Elimination"],
        "text": (
            "Systematic elimination for logic puzzles:\n\n"
            "1. LIST all possible states explicitly\n"
            "2. For each piece of information, ELIMINATE impossible states\n"
            "3. Check what remains — if one answer, done; if multiple, "
            "need more info\n\n"
            "Common traps:\n"
            "- Assuming a conclusion before checking all branches\n"
            "- Forgetting that 'not proven true' ≠ 'proven false'\n"
            "- Mixing up the CONTAINER that holds the result\n"
            "   Example: 'You have 4 gallons' — WHERE? In which jug?\n"
            "- Off-by-one in counting (fencepost errors)\n"
            "- Confusing 'average case' with 'worst case'\n\n"
            "Verification strategy:\n"
            "- After solving, TRACE through your answer step by step\n"
            "- Check the answer makes physical/logical sense\n"
            "  (Can a 3-gallon jug hold 4 gallons? No.)\n"
            "- Count: does your solution actually use the right number "
            "of steps/weighings/moves?\n"
            "- Edge cases: does it work for the worst case, not just "
            "a lucky case?"
        ),
    },
    {
        "id": "reasoning:problem-solving:0007",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:binary", "topic:number", "topic:conversion", "topic:math", "topic:base"],
        "source_id": "problem-solving",
        "source_path": "hand-written/math.md",
        "heading_path": ["Math", "Binary Number Conversion"],
        "text": (
            "Converting decimal to binary — method:\n\n"
            "Repeatedly divide by 2, record remainders (read bottom-to-top):\n"
            "730 ÷ 2 = 365 remainder 0\n"
            "365 ÷ 2 = 182 remainder 1\n"
            "182 ÷ 2 = 91  remainder 0\n"
            "91  ÷ 2 = 45  remainder 1\n"
            "45  ÷ 2 = 22  remainder 1\n"
            "22  ÷ 2 = 11  remainder 0\n"
            "11  ÷ 2 = 5   remainder 1\n"
            "5   ÷ 2 = 2   remainder 1\n"
            "2   ÷ 2 = 1   remainder 0\n"
            "1   ÷ 2 = 0   remainder 1\n"
            "Read bottom-to-top: 1011011010\n\n"
            "Verify: 512 + 128 + 64 + 16 + 8 + 2 = 730 ✓\n\n"
            "Powers of 2 reference:\n"
            "2^0=1, 2^1=2, 2^2=4, 2^3=8, 2^4=16, 2^5=32\n"
            "2^6=64, 2^7=128, 2^8=256, 2^9=512, 2^10=1024\n\n"
            "Quick check: the highest power of 2 ≤ N tells you the "
            "number of binary digits. 512 ≤ 730 < 1024, so 730 is "
            "a 10-bit number (starts with 1)."
        ),
    },
    {
        "id": "reasoning:problem-solving:0008",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:complexity", "topic:analysis", "topic:big", "topic:tradeoff"],
        "source_id": "problem-solving",
        "source_path": "hand-written/complexity.md",
        "heading_path": ["Analysis", "Complexity Reasoning"],
        "text": (
            "How to reason about time/space complexity:\n\n"
            "1. IDENTIFY the input size variable (n = length of array, "
            "V = number of vertices, etc.)\n\n"
            "2. COUNT nested operations:\n"
            "   - Single loop over n: O(n)\n"
            "   - Nested loop over n: O(n²)\n"
            "   - Loop that halves each step: O(log n)\n"
            "   - Recursion that branches k ways, depth d: O(k^d)\n\n"
            "3. SPACE = memory allocated that grows with input:\n"
            "   - New array of size n: O(n) space\n"
            "   - Recursion depth d: O(d) stack space\n"
            "   - Hash set of visited nodes: O(n) space\n\n"
            "4. AMORTIZED analysis: occasional expensive ops averaged out.\n"
            "   list.append() is O(1) amortized even though resizing is O(n)\n\n"
            "Common mistakes:\n"
            "- Forgetting hidden loops: 'x in list' is O(n), not O(1)\n"
            "- String concatenation in a loop: O(n²) total (use ''.join())\n"
            "- Ignoring the cost of sorting: sorted() is O(n log n)\n"
            "- Assuming dict operations are free: they're O(1) average "
            "but O(n) worst case due to hash collisions"
        ),
    },
]

# ═══════════════════════════════════════════════════════════════════════
# EXPANSION ROUND 2 — NEW CODING ENTRIES
# Topics: backtracking, union-find, trie, regex, interview patterns,
#         Flask, sliding window, two-pointer
# ═══════════════════════════════════════════════════════════════════════

NEW_CODING_2: list[dict] = [
    # ── Backtracking ─────────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0016",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:backtracking", "topic:recursion", "topic:dfs", "topic:permutation"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/backtracking.md",
        "heading_path": ["Algorithms", "Backtracking", "Template + Examples"],
        "text": (
            "Backtracking = recursion + undo. Try a choice, recurse, undo the choice.\n\n"
            "TEMPLATE:\n"
            "```python\n"
            "def backtrack(state, choices):\n"
            "    if is_solution(state):\n"
            "        results.append(state[:])  # copy, not reference\n"
            "        return\n"
            "    for choice in choices:\n"
            "        if is_valid(state, choice):\n"
            "            state.append(choice)   # make choice\n"
            "            backtrack(state, remaining_choices(choices, choice))\n"
            "            state.pop()            # UNDO choice\n"
            "```\n\n"
            "PERMUTATIONS of [1,2,3]:\n"
            "```python\n"
            "def permutations(nums):\n"
            "    result = []\n"
            "    def bt(current, remaining):\n"
            "        if not remaining:\n"
            "            result.append(current[:])\n"
            "            return\n"
            "        for i, n in enumerate(remaining):\n"
            "            current.append(n)\n"
            "            bt(current, remaining[:i] + remaining[i+1:])\n"
            "            current.pop()\n"
            "    bt([], nums)\n"
            "    return result\n"
            "```\n\n"
            "SUBSETS (power set):\n"
            "```python\n"
            "def subsets(nums):\n"
            "    result = []\n"
            "    def bt(start, current):\n"
            "        result.append(current[:])\n"
            "        for i in range(start, len(nums)):\n"
            "            current.append(nums[i])\n"
            "            bt(i + 1, current)\n"
            "            current.pop()\n"
            "    bt(0, [])\n"
            "    return result\n"
            "```\n\n"
            "Time: O(n!) for permutations, O(2^n) for subsets. "
            "Prune early with is_valid() checks to cut branches."
        ),
    },
    # ── Union-Find ───────────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0017",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:union-find", "topic:union", "topic:find", "topic:disjoint-set", "topic:disjoint", "topic:graph", "topic:kruskal", "topic:cycle", "topic:connected"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/union_find.md",
        "heading_path": ["Data Structures", "Union-Find (Disjoint Set Union)"],
        "text": (
            "Union-Find tracks which elements are in the same group. "
            "Two operations: find (which group?) and union (merge groups). "
            "Used for: connected components, cycle detection, Kruskal's MST.\n\n"
            "```python\n"
            "class UnionFind:\n"
            "    def __init__(self, n):\n"
            "        self.parent = list(range(n))  # each node is its own parent\n"
            "        self.rank = [0] * n            # tree height (for union by rank)\n"
            "\n"
            "    def find(self, x):\n"
            "        # Path compression: flatten the tree as we search\n"
            "        if self.parent[x] != x:\n"
            "            self.parent[x] = self.find(self.parent[x])\n"
            "        return self.parent[x]\n"
            "\n"
            "    def union(self, x, y):\n"
            "        px, py = self.find(x), self.find(y)\n"
            "        if px == py:\n"
            "            return False  # already same group — adding edge = CYCLE\n"
            "        # Union by rank: attach smaller tree under larger\n"
            "        if self.rank[px] < self.rank[py]:\n"
            "            px, py = py, px\n"
            "        self.parent[py] = px\n"
            "        if self.rank[px] == self.rank[py]:\n"
            "            self.rank[px] += 1\n"
            "        return True  # successfully merged\n"
            "\n"
            "    def connected(self, x, y):\n"
            "        return self.find(x) == self.find(y)\n"
            "```\n\n"
            "CYCLE DETECTION in undirected graph:\n"
            "```python\n"
            "def has_cycle(n, edges):\n"
            "    uf = UnionFind(n)\n"
            "    for u, v in edges:\n"
            "        if not uf.union(u, v):  # already connected = cycle\n"
            "            return True\n"
            "    return False\n"
            "```\n\n"
            "Time: O(α(n)) per operation — effectively O(1). α is inverse Ackermann, "
            "never exceeds 4 in practice."
        ),
    },
    # ── Trie ─────────────────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0018",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:trie", "topic:prefix-tree", "topic:prefix", "topic:autocomplete", "topic:search", "topic:dictionary"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/trie.md",
        "heading_path": ["Data Structures", "Trie (Prefix Tree)"],
        "text": (
            "A Trie stores strings character-by-character. Perfect for: "
            "autocomplete, prefix search, word validation, IP routing.\n\n"
            "```python\n"
            "class TrieNode:\n"
            "    __slots__ = ('children', 'is_end')\n"
            "    def __init__(self):\n"
            "        self.children: dict[str, 'TrieNode'] = {}\n"
            "        self.is_end = False  # marks end of a complete word\n"
            "\n"
            "class Trie:\n"
            "    def __init__(self):\n"
            "        self.root = TrieNode()\n"
            "\n"
            "    def insert(self, word: str) -> None:\n"
            "        node = self.root\n"
            "        for ch in word:\n"
            "            if ch not in node.children:\n"
            "                node.children[ch] = TrieNode()\n"
            "            node = node.children[ch]\n"
            "        node.is_end = True\n"
            "\n"
            "    def search(self, word: str) -> bool:\n"
            "        node = self._traverse(word)\n"
            "        return node is not None and node.is_end\n"
            "\n"
            "    def starts_with(self, prefix: str) -> bool:\n"
            "        return self._traverse(prefix) is not None\n"
            "\n"
            "    def autocomplete(self, prefix: str) -> list[str]:\n"
            "        node = self._traverse(prefix)\n"
            "        if node is None:\n"
            "            return []\n"
            "        results = []\n"
            "        self._dfs(node, list(prefix), results)\n"
            "        return results\n"
            "\n"
            "    def _traverse(self, s: str):\n"
            "        node = self.root\n"
            "        for ch in s:\n"
            "            if ch not in node.children:\n"
            "                return None\n"
            "            node = node.children[ch]\n"
            "        return node\n"
            "\n"
            "    def _dfs(self, node, path, results):\n"
            "        if node.is_end:\n"
            "            results.append(''.join(path))\n"
            "        for ch, child in node.children.items():\n"
            "            path.append(ch)\n"
            "            self._dfs(child, path, results)\n"
            "            path.pop()\n"
            "```\n\n"
            "Space: O(ALPHABET_SIZE * max_word_length * num_words). "
            "Time: O(L) per insert/search where L = word length."
        ),
    },
    # ── Sliding Window ───────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0019",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:sliding-window", "topic:sliding", "topic:window", "topic:array", "topic:interview", "topic:two-pointer", "topic:pointer", "topic:subarray"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/sliding_window.md",
        "heading_path": ["Algorithms", "Sliding Window + Two-Pointer Patterns"],
        "text": (
            "Sliding window: maintain a window [left, right] over an array, "
            "expand right and shrink left to find optimal subarray. O(n).\n\n"
            "FIXED-SIZE WINDOW (max sum of k elements):\n"
            "```python\n"
            "def max_sum_k(nums, k):\n"
            "    window = sum(nums[:k])\n"
            "    best = window\n"
            "    for i in range(k, len(nums)):\n"
            "        window += nums[i] - nums[i - k]  # slide: add right, drop left\n"
            "        best = max(best, window)\n"
            "    return best\n"
            "```\n\n"
            "VARIABLE WINDOW (longest substring with at most k distinct chars):\n"
            "```python\n"
            "from collections import defaultdict\n"
            "def longest_k_distinct(s, k):\n"
            "    counts = defaultdict(int)\n"
            "    left = best = 0\n"
            "    for right, ch in enumerate(s):\n"
            "        counts[ch] += 1\n"
            "        while len(counts) > k:      # window invalid — shrink left\n"
            "            counts[s[left]] -= 1\n"
            "            if counts[s[left]] == 0:\n"
            "                del counts[s[left]]\n"
            "            left += 1\n"
            "        best = max(best, right - left + 1)\n"
            "    return best\n"
            "```\n\n"
            "TWO-POINTER (pair that sums to target in sorted array):\n"
            "```python\n"
            "def two_sum_sorted(nums, target):\n"
            "    left, right = 0, len(nums) - 1\n"
            "    while left < right:\n"
            "        s = nums[left] + nums[right]\n"
            "        if s == target:\n"
            "            return (left, right)\n"
            "        elif s < target:\n"
            "            left += 1\n"
            "        else:\n"
            "            right -= 1\n"
            "    return None\n"
            "```\n\n"
            "FAST/SLOW POINTER (detect cycle in linked list):\n"
            "```python\n"
            "def has_cycle(head):\n"
            "    slow = fast = head\n"
            "    while fast and fast.next:\n"
            "        slow = slow.next\n"
            "        fast = fast.next.next\n"
            "        if slow is fast:\n"
            "            return True\n"
            "    return False\n"
            "```"
        ),
    },
    # ── Regex ────────────────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0020",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:regex", "topic:re", "topic:pattern", "topic:string"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/regex.md",
        "heading_path": ["Python Patterns", "Regular Expressions", "Core Patterns + Gotchas"],
        "text": (
            "Python regex via the `re` module. Compile patterns you reuse.\n\n"
            "CORE SYNTAX:\n"
            "  .      any char except newline\n"
            "  \\d     digit [0-9]\n"
            "  \\w     word char [a-zA-Z0-9_]\n"
            "  \\s     whitespace\n"
            "  ^/$    start/end of string\n"
            "  *      0 or more (greedy)\n"
            "  +      1 or more (greedy)\n"
            "  ?      0 or 1 / makes quantifier lazy\n"
            "  {n,m}  n to m repetitions\n"
            "  (...)  capture group\n"
            "  (?:...) non-capturing group\n"
            "  (?=...) positive lookahead\n"
            "  [abc]  character class\n"
            "  |      alternation (OR)\n\n"
            "COMMON PATTERNS:\n"
            "```python\n"
            "import re\n"
            "\n"
            "# Compile once, use many times\n"
            "EMAIL_RE = re.compile(r'[\\w.+-]+@[\\w-]+\\.[\\w.-]+')\n"
            "URL_RE   = re.compile(r'https?://[^\\s]+')\n"
            "INT_RE   = re.compile(r'-?\\d+')\n"
            "\n"
            "# Match vs search vs findall\n"
            "re.match(r'\\d+', '123abc')   # matches at START only -> Match\n"
            "re.search(r'\\d+', 'abc123')  # matches ANYWHERE -> Match\n"
            "re.findall(r'\\d+', 'a1b22')  # all matches -> ['1', '22']\n"
            "\n"
            "# Groups\n"
            "m = re.search(r'(\\w+)@(\\w+)\\.', 'user@host.com')\n"
            "m.group(1)  # 'user'\n"
            "m.group(2)  # 'host'\n"
            "\n"
            "# Named groups (cleaner)\n"
            "m = re.search(r'(?P<user>\\w+)@(?P<domain>\\w+)', 'x@y')\n"
            "m.group('user')   # 'x'\n"
            "\n"
            "# Substitution\n"
            "re.sub(r'\\s+', ' ', 'too  many   spaces')  # 'too many spaces'\n"
            "\n"
            "# Raw strings: ALWAYS use r'' for regex to avoid double-escaping\n"
            "```\n\n"
            "GOTCHAS:\n"
            "- Greedy by default: .* matches as MUCH as possible. Use .*? for lazy.\n"
            "- re.DOTALL makes . match newlines too\n"
            "- re.IGNORECASE for case-insensitive\n"
            "- re.MULTILINE makes ^ and $ match line starts/ends, not just string"
        ),
    },
    # ── Dynamic Programming Patterns ─────────────────────────────────
    {
        "id": "coding:cs-patterns:0021",
        "tags": ["src:cs-patterns", "cat:patterns", "topic:dynamic-programming", "topic:dynamic", "topic:programming", "topic:dp", "topic:memoization", "topic:tabulation", "topic:interview", "topic:knapsack", "topic:lcs", "topic:subsequence"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/dp.md",
        "heading_path": ["Algorithms", "Dynamic Programming", "Common Patterns"],
        "text": (
            "DP = overlapping subproblems + optimal substructure. "
            "Two styles: top-down (memoization) and bottom-up (tabulation).\n\n"
            "TOP-DOWN with @cache (Python 3.9+):\n"
            "```python\n"
            "from functools import cache\n"
            "\n"
            "# Fibonacci\n"
            "@cache\n"
            "def fib(n):\n"
            "    if n < 2: return n\n"
            "    return fib(n-1) + fib(n-2)\n"
            "\n"
            "# Coin change: min coins to make amount\n"
            "@cache\n"
            "def coin_change(coins, amount):\n"
            "    if amount == 0: return 0\n"
            "    if amount < 0: return float('inf')\n"
            "    return 1 + min(coin_change(coins, amount - c) for c in coins)\n"
            "```\n\n"
            "BOTTOM-UP tabulation (usually faster, no recursion limit):\n"
            "```python\n"
            "# 0/1 Knapsack: max value with weight limit W\n"
            "def knapsack(weights, values, W):\n"
            "    n = len(weights)\n"
            "    dp = [[0] * (W + 1) for _ in range(n + 1)]\n"
            "    for i in range(1, n + 1):\n"
            "        for w in range(W + 1):\n"
            "            dp[i][w] = dp[i-1][w]  # don't take item i\n"
            "            if weights[i-1] <= w:\n"
            "                dp[i][w] = max(dp[i][w],\n"
            "                               values[i-1] + dp[i-1][w - weights[i-1]])\n"
            "    return dp[n][W]\n"
            "\n"
            "# Longest Common Subsequence\n"
            "def lcs(s1, s2):\n"
            "    m, n = len(s1), len(s2)\n"
            "    dp = [[0] * (n + 1) for _ in range(m + 1)]\n"
            "    for i in range(1, m + 1):\n"
            "        for j in range(1, n + 1):\n"
            "            if s1[i-1] == s2[j-1]:\n"
            "                dp[i][j] = dp[i-1][j-1] + 1\n"
            "            else:\n"
            "                dp[i][j] = max(dp[i-1][j], dp[i][j-1])\n"
            "    return dp[m][n]\n"
            "```\n\n"
            "PATTERN RECOGNITION:\n"
            "- 'count ways' / 'minimum steps' -> DP\n"
            "- Recurrence over index: dp[i] = f(dp[i-1], ...)\n"
            "- Recurrence over two strings: dp[i][j] = f(dp[i-1][j-1], ...)\n"
            "- Check if problem has OPTIMAL SUBSTRUCTURE first — not every optimization is DP"
        ),
    },
    # ── Flask Patterns ───────────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0022",
        "tags": ["src:cs-patterns", "cat:web", "topic:flask", "topic:blueprint", "topic:app-factory", "topic:api"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/flask.md",
        "heading_path": ["Web Frameworks", "Flask", "App Factory + Blueprints"],
        "text": (
            "Flask = lightweight WSGI web framework. Best pattern: App Factory.\n\n"
            "APP FACTORY (allows testing, multiple configs):\n"
            "```python\n"
            "# app/__init__.py\n"
            "from flask import Flask\n"
            "from .config import Config\n"
            "\n"
            "def create_app(config=Config):\n"
            "    app = Flask(__name__)\n"
            "    app.config.from_object(config)\n"
            "\n"
            "    # Register blueprints\n"
            "    from .api import bp as api_bp\n"
            "    app.register_blueprint(api_bp, url_prefix='/api')\n"
            "\n"
            "    # Register extensions\n"
            "    db.init_app(app)\n"
            "    return app\n"
            "```\n\n"
            "BLUEPRINT (groups related routes):\n"
            "```python\n"
            "# app/api/__init__.py\n"
            "from flask import Blueprint\n"
            "bp = Blueprint('api', __name__)\n"
            "from . import routes  # import routes so they register\n"
            "\n"
            "# app/api/routes.py\n"
            "from flask import jsonify, request, abort\n"
            "from . import bp\n"
            "\n"
            "@bp.route('/users', methods=['GET'])\n"
            "def get_users():\n"
            "    return jsonify({'users': []})\n"
            "\n"
            "@bp.route('/users/<int:user_id>', methods=['GET'])\n"
            "def get_user(user_id):\n"
            "    user = User.query.get_or_404(user_id)\n"
            "    return jsonify(user.to_dict())\n"
            "```\n\n"
            "ERROR HANDLERS:\n"
            "```python\n"
            "@app.errorhandler(404)\n"
            "def not_found(e):\n"
            "    return jsonify(error=str(e)), 404\n"
            "\n"
            "@app.errorhandler(500)\n"
            "def server_error(e):\n"
            "    return jsonify(error='Internal server error'), 500\n"
            "```\n\n"
            "KEY DIFFERENCES vs FastAPI:\n"
            "- Flask: synchronous by default, explicit serialization with jsonify()\n"
            "- FastAPI: async by default, automatic JSON serialization, auto-docs\n"
            "- Flask needs flask-login, flask-sqlalchemy etc. FastAPI integrates directly.\n"
            "- Use Flask for: mature ecosystems, simpler apps. "
            "FastAPI for: async APIs, type-safe, auto-docs."
        ),
    },
    # ── Type Hints Advanced ──────────────────────────────────────────
    {
        "id": "coding:cs-patterns:0023",
        "tags": ["src:cs-patterns", "cat:typing", "topic:type-hints", "topic:generics", "topic:protocol", "topic:typing"],
        "source_id": "cs-patterns",
        "source_path": "hand-written/type_hints.md",
        "heading_path": ["Python Patterns", "Type Hints", "Advanced Patterns"],
        "text": (
            "Python type hints for correctness + IDE support. Use mypy or pyright.\n\n"
            "BASICS:\n"
            "```python\n"
            "from typing import Optional, Union, Any\n"
            "from collections.abc import Callable, Iterator, Generator\n"
            "\n"
            "def greet(name: str, times: int = 1) -> str:\n"
            "    return name * times\n"
            "\n"
            "# Python 3.10+ union syntax\n"
            "def foo(x: int | str | None) -> list[int]: ...\n"
            "```\n\n"
            "GENERICS (reusable typed containers):\n"
            "```python\n"
            "from typing import TypeVar, Generic\n"
            "T = TypeVar('T')\n"
            "\n"
            "class Stack(Generic[T]):\n"
            "    def __init__(self) -> None:\n"
            "        self._items: list[T] = []\n"
            "    def push(self, item: T) -> None:\n"
            "        self._items.append(item)\n"
            "    def pop(self) -> T:\n"
            "        return self._items.pop()\n"
            "\n"
            "stack: Stack[int] = Stack()\n"
            "```\n\n"
            "PROTOCOL (structural typing — duck typing with checks):\n"
            "```python\n"
            "from typing import Protocol, runtime_checkable\n"
            "\n"
            "@runtime_checkable\n"
            "class Drawable(Protocol):\n"
            "    def draw(self) -> None: ...\n"
            "\n"
            "def render(obj: Drawable) -> None:\n"
            "    obj.draw()  # works for ANY object with .draw()\n"
            "```\n\n"
            "CALLABLE + OVERLOAD:\n"
            "```python\n"
            "from typing import overload\n"
            "\n"
            "Handler = Callable[[str, int], bool]\n"
            "\n"
            "@overload\n"
            "def process(x: int) -> int: ...\n"
            "@overload\n"
            "def process(x: str) -> str: ...\n"
            "def process(x):\n"
            "    return x\n"
            "```\n\n"
            "TypedDict for dicts with known shapes:\n"
            "```python\n"
            "from typing import TypedDict\n"
            "class User(TypedDict):\n"
            "    name: str\n"
            "    age: int\n"
            "```"
        ),
    },
]

# ═══════════════════════════════════════════════════════════════════════
# EXPANSION ROUND 2 — NEW REASONING ENTRIES
# Topics: debugging loops, estimation, when-to-stop, trade-off matrices
# ═══════════════════════════════════════════════════════════════════════

NEW_REASONING_2: list[dict] = [
    {
        "id": "reasoning:problem-solving:0012",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:performance", "topic:slow", "topic:complexity", "topic:nested", "topic:loop", "topic:optimization", "topic:bottleneck"],
        "source_id": "problem-solving",
        "source_path": "hand-written/performance_debugging.md",
        "heading_path": ["Debugging", "Why Is My Code Slow?"],
        "text": (
            "WHEN CODE IS SLOW — SYSTEMATIC DIAGNOSIS:\n\n"
            "Step 1: IDENTIFY the complexity.\n"
            "- Single loop over n items: O(n) — fast\n"
            "- NESTED loops over n items: O(n²) — this is usually the problem\n"
            "  1000² = 1M ops (instant), 100,000² = 10 BILLION ops (minutes to hours)\n"
            "- Triple nested: O(n³) — unusable beyond ~1000 items\n\n"
            "Step 2: FIND the nested loop.\n"
            "- Look for: for x in items: for y in items: ...\n"
            "- Hidden nests: 'if x in list' inside a loop is O(n²) — use a set!\n"
            "- String concatenation in loop: O(n²) total — use ''.join()\n\n"
            "Step 3: ELIMINATE the inner loop.\n"
            "- Searching? Replace inner loop with dict/set lookup → O(1) per check\n"
            "  Before: for x in a: for y in b: if x==y → O(n²)\n"
            "  After:  b_set = set(b); for x in a: if x in b_set → O(n)\n"
            "- Sorting-based? Sort first O(n log n), then single pass O(n)\n"
            "- Counting? Use collections.Counter → O(n)\n"
            "- Finding pairs? Use a hash map → O(n)\n\n"
            "NEVER: add more hardware to fix an O(n²) problem. Fix the algorithm.\n"
            "NEVER: say 'use multiprocessing' for an O(n²) loop — that's 4x faster "
            "at best, still O(n²). Fix the algorithm."
        ),
    },
    {
        "id": "reasoning:problem-solving:0009",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:retry", "topic:failure", "topic:debugging", "topic:stuck"],
        "source_id": "problem-solving",
        "source_path": "hand-written/retry_logic.md",
        "heading_path": ["Debugging", "When to Stop Retrying"],
        "text": (
            "WHEN TO STOP AND ASK FOR HELP:\n\n"
            "Retry limit rule: if you've tried the same approach 3+ times and "
            "gotten the same error, STOP. The approach is wrong, not the implementation.\n\n"
            "Signs you're in a retry loop:\n"
            "- Same error message after 3+ changes\n"
            "- Changes getting more speculative ('maybe if I try X...')\n"
            "- You're not sure WHY the last attempt failed\n"
            "- The fix feels like guessing\n\n"
            "What to do instead:\n"
            "1. STOP writing code. Step back.\n"
            "2. Re-read the error from scratch. What does it ACTUALLY say?\n"
            "3. Check your assumptions. Did you assume a variable has a type it doesn't?\n"
            "4. Read the relevant source code or docs — don't guess at APIs.\n"
            "5. If still stuck after step 4: say so clearly. Tell the user:\n"
            "   'I've tried X approaches and keep getting Y. I need more info: [specific question]'\n\n"
            "NEVER: keep writing bad code hoping it compiles. "
            "NEVER: silently write code you know is wrong. "
            "ALWAYS: be honest when you're stuck."
        ),
    },
    {
        "id": "reasoning:problem-solving:0010",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:estimation", "topic:fermi", "topic:rough-math"],
        "source_id": "problem-solving",
        "source_path": "hand-written/estimation.md",
        "heading_path": ["Reasoning", "Estimation and Fermi Problems"],
        "text": (
            "Estimation = get in the right ballpark without exact calculation.\n\n"
            "PROCESS:\n"
            "1. Break into knowable pieces\n"
            "2. Estimate each piece (round aggressively)\n"
            "3. Multiply/add with sanity checks\n\n"
            "USEFUL NUMBERS to memorize:\n"
            "- Seconds in a day: 86,400 (~10^5)\n"
            "- Seconds in a year: ~3 × 10^7\n"
            "- RAM read: ~100ns. Disk read: ~10ms. Network: ~100ms\n"
            "- 1 million ops/sec for pure Python. 100M+ for C/compiled.\n"
            "- 1GB = 10^9 bytes. 1 char = 1 byte. 1 int = 4-8 bytes.\n\n"
            "CODING ESTIMATION:\n"
            "- 'Will this be fast enough?' → estimate ops needed, compare to rate\n"
            "- 'How much memory?' → estimate items × bytes per item\n"
            "- 'How long will the loop run?' → items × cost per item\n\n"
            "Example: process 1M records at 10ms each = 10,000 seconds = too slow. "
            "Need batch/async/different approach."
        ),
    },
    {
        "id": "reasoning:problem-solving:0011",
        "tags": ["src:problem-solving", "cat:problem-solving", "topic:trade-off", "topic:decision", "topic:architecture"],
        "source_id": "problem-solving",
        "source_path": "hand-written/tradeoffs.md",
        "heading_path": ["Design", "Trade-off Matrix for Common Decisions"],
        "text": (
            "When choosing between approaches, use a trade-off matrix.\n\n"
            "MEMORY vs SPEED:\n"
            "- Cache results (memoize) → faster but more memory\n"
            "- Recompute on demand → less memory but slower\n"
            "- Rule: cache when called frequently with same inputs\n\n"
            "SIMPLICITY vs FLEXIBILITY:\n"
            "- Hard-code → simple but brittle\n"
            "- Config-driven → flexible but complex\n"
            "- Rule: hard-code until you need the second case\n\n"
            "SYNC vs ASYNC:\n"
            "- Sync → simple, sequential, easy to debug\n"
            "- Async → concurrent, complex, needed for I/O-heavy work\n"
            "- Rule: start sync. Add async when you hit I/O bottlenecks.\n\n"
            "SQL vs NoSQL:\n"
            "- SQL → relational data, joins, ACID guarantees, schema enforced\n"
            "- NoSQL → flexible schema, horizontal scale, eventual consistency\n"
            "- Rule: default to SQL. Switch to NoSQL when you outgrow it.\n\n"
            "MONOLITH vs MICROSERVICES:\n"
            "- Monolith → simple deploy, easy debugging, works for most teams\n"
            "- Microservices → independent scale, complex ops, teams > 50 engineers\n"
            "- Rule: start monolith. Extract services when a team owns a boundary."
        ),
    },
]


def main() -> None:
    """Append new entries to both bibles and rebuild indexes."""
    all_coding = NEW_CODING + NEW_CODING_2
    all_reasoning = NEW_REASONING + NEW_REASONING_2
    for bible_name, new_entries in [("coding", all_coding), ("reasoning", all_reasoning)]:
        bible_path = BIBLES_DIR / f"{bible_name}.bible.json"
        index_path = BIBLES_DIR / f"{bible_name}.index.json"

        # Load existing bible.
        existing = json.loads(bible_path.read_text(encoding="utf-8"))
        existing_ids = {e["id"] for e in existing}

        # Add new entries (skip duplicates by ID).
        added = 0
        for entry in new_entries:
            if entry["id"] not in existing_ids:
                existing.append(entry)
                existing_ids.add(entry["id"])
                added += 1

        # Write updated bible.
        bible_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )
        print(f"{bible_name}: added {added} entries (total: {len(existing)})")

        # Rebuild index.
        index: dict[str, list[str]] = {}
        for entry in existing:
            for tag in entry["tags"]:
                index.setdefault(tag, []).append(entry["id"])
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )
        print(f"{bible_name}: rebuilt index ({len(index)} tags)")


if __name__ == "__main__":
    main()
