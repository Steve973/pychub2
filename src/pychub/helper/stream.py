from functools import reduce as _reduce
from itertools import islice, tee, groupby
from typing import Any


class Stream:
    """
    Provides a representation of a lazily evaluated stream for functional-style operations.

    This class enables stream-style, iterative transformations, and terminal operations on an iterable.
    It supports lazy evaluation, allowing computation to be deferred until explicitly needed. The stream
    can perform operations such as mapping, filtering, and flattening, and can also terminate into a list,
    set, or count the number of elements.

    Attributes:
        _it (Iterable): The iterable from which the stream is constructed.
    """

    _it: Any

    def __init__(self, iterable):
        """
        Initializes an iterator for the given iterable.

        Args:
            iterable (Iterable): An iterable object which needs to be converted into
                an iterator.
        """
        self._it = iter(iterable)

    def map(self, fn):
        """
        Applies a function to each element of the stream and returns a new stream with the transformed elements.

        This method transforms the current stream by applying the provided function to each of its elements.
        The transformation is lazy, which means it is not executed until the elements of the stream are consumed.

        Args:
            fn (Callable): A function that takes an element from the stream as an argument
                and returns the transformed element.

        Returns:
            Stream: A new Stream containing the transformed elements.
        """
        return Stream(map(fn, self._it))

    def filter(self, pred):
        """
        Filters elements of the stream based on a predicate function.

        The method applies the given predicate function to each element in the
        stream and filters out elements that do not satisfy the predicate.
        Returns a new Stream containing only the elements that meet the
        predicate criteria.

        Args:
            pred (Callable[[Any], bool]): A callable which takes an element from
                the iterable and returns a boolean indicating whether the
                element should be included in the resulting filtered Stream.

        Returns:
            Stream: A new Stream instance containing only the elements that
            satisfy the predicate function.
        """
        return Stream(filter(pred, self._it))

    def flat_map(self, fn):
        """
        Transforms each element of the input iterable using the provided function
        and flattens the resulting iterables into a single iterable.

        The provided function is applied to every element of the stream, and the
        iterables returned by the function are then flattened into a single unified
        stream of elements.

        Args:
            fn: A function that accepts a single input and returns an iterable.
                This function is applied to each element of the stream.

        Returns:
            Stream: A new stream containing the flattened elements after applying
            the provided function to each element of the original stream.
        """
        # fn returns iterable for each item
        return Stream(x for item in self._it for x in fn(item))

    def distinct(self):
        """
        Filters the stream to include only distinct elements, maintaining the original order.

        The method ensures that each element occurs only once in the resulting stream
        by leveraging a set to keep track of seen elements.

        Returns:
            Stream: A new stream containing only distinct elements from the original stream.
        """
        seen = set()

        def mark_seen(x: Any) -> bool:
            """
            Marks an item as seen by adding it to a set of seen items.

            Args:
                x (Any): The item to mark as seen.

            Returns:
                bool: Always returns True after adding the item to the set.
            """
            seen.add(x)
            return True

        return Stream(x for x in self._it if x not in seen and mark_seen(x))

    def peek(self, fn):
        """
        Wraps an existing iterable, allowing a function to be applied to each element for side effects,
        while preserving the original items of the iterable. This allows for inspection of elements
        without consuming or altering them within the generator.

        Args:
            fn (Callable[[Any], None]): A function that takes an element of the iterable as input
                and performs a side effect. This function does not modify or consume the element.

        Returns:
            Stream: A new stream where the function is applied to each item in the iterable as a
                side effect before yielding the original item.
        """
        def generator():
            """
            A generator function that processes and yields values from an iterable.

            This function iterates over the elements of an internal iterable,
            applies a function to each element, and yields the processed element.

            Yields:
                Any: The next value from the iterable after being processed by the function.
            """
            for x in self._it:
                fn(x)
                yield x

        return Stream(generator())

    def sorted(self, key=None, reverse=False):
        """
        Returns a new instance of the Stream class with the elements sorted.

        This method sorts the elements of the current stream using the specified
        key function and reverse indicator, and returns a new stream instance with
        these sorted elements.

        Args:
            key (Callable, optional): A function of one argument that is used to
                extract a comparison key from each element in the stream. Defaults
                to None, which means the natural ordering will be used.
            reverse (bool, optional): If True, the elements are sorted in
                descending order. Defaults to False for ascending order.

        Returns:
            Stream: A new Stream object containing the sorted elements of the
            original stream.
        """
        return Stream(sorted(self._it, key=key, reverse=reverse))

    def limit(self, n):
        """
        Limits the stream to the first `n` elements.

        Args:
            n (int): The number of elements to include in the limited stream.

        Returns:
            Stream: A new Stream instance containing the first `n` elements.
        """
        return Stream(islice(self._it, n))

    def skip(self, n):
        """
        Skips the first `n` elements from the stream and yields the rest.

        This function consumes the initial `n` elements of the internal iterable and
        starts yielding elements from that point onwards. If `n` is greater than the
        total number of elements in the iterable, it will simply return an exhausted
        stream.

        Args:
            n: The number of elements to skip from the beginning of the stream.

        Returns:
            Stream: A new Stream object that yields elements after skipping the first
            `n` elements.
        """
        # Consume n elements, then yield rest
        def generator():
            it = self._it
            for _ in range(n):
                next(it, None)
            yield from it

        return Stream(generator())

    # Terminal ops
    def to_list(self):
        """
        Converts an internal iterable into a list.

        This method transforms the internal iterable object into a list and returns
        it. The internal attribute `_it` is utilized for this conversion.

        Returns:
            list: A list representation of the internal iterable object.
        """
        return list(self._it)

    def to_set(self):
        """Convert the internal iterable to a set.

        This method transforms the internal iterable into a set, which ensures
        unique elements and removes duplicates.

        Returns:
            set: A set containing the unique elements of the internal iterable.
        """
        return set(self._it)

    def count(self):
        """
        Counts the number of items in an internal iterable.

        This method iterates through the internal iterable `_it` and counts the
        number of items present in it. The count is computed by summing up 1 for
        each item in the iterable.

        Returns:
            int: The total count of items in the iterable.
        """
        return sum(1 for _ in self._it)

    def find_first(self):
        """
        Finds and returns the first element from the iterator.

        This method retrieves the first element of an internal iterator. If the
        iterator is empty, it will return None.

        Returns:
            Any: The first element of the iterator if available, otherwise None.
        """
        try:
            return next(self._it)
        except StopIteration:
            return None

    def any_match(self, pred):
        """
        Determines if any element in the iterable satisfies the given predicate.

        This method evaluates the elements in the iterable using the provided
        predicate function. If at least one element satisfies the predicate, it
        returns True. Otherwise, it returns False.

        Args:
            pred (Callable[[Any], bool]): A predicate function that takes an element
                from the iterable and returns a boolean indicating whether the
                element satisfies the condition.

        Returns:
            bool: True if at least one element satisfies the predicate, False otherwise.
        """
        return any(pred(x) for x in self._it)

    def all_match(self, pred):
        """
        Checks if all elements in the iterable satisfy the given predicate.

        This method evaluates the predicate function for each element in the
        iterable and checks if all evaluations return True. If the predicate
        evaluates to False for any element, the method returns False. If the
        iterable is empty, this method returns True.

        Args:
            pred (Callable): A function that takes an element of the iterable
                as input and returns a boolean.

        Returns:
            bool: True if the predicate is True for all elements, otherwise False.
        """
        return all(pred(x) for x in self._it)

    def none_match(self, pred):
        """
        Check if no elements in the iterable match the given predicate.

        Args:
            pred: A callable returning a boolean value, used to test each element
                in the iterable.

        Returns:
            bool: True if no elements satisfy the predicate, otherwise False.
        """
        return not any(pred(x) for x in self._it)

    def reduce(self, fn, initializer=None):
        """
        Reduces the iterable to a single value by applying the specified function
        cumulatively to the items in the iterable.

        This method applies a binary function `fn` to the items of the iterable from left
        to right, using an optional initializer if provided. If no initializer is supplied,
        the first item of the iterable is used as the initial value.

        Args:
            fn (Callable[[Any, Any], Any]): A binary function that will be applied
                cumulatively to the items in the iterable.
            initializer (Any, optional): An optional initial value to start the reduction.
                If provided, it is used as the initial value; otherwise, the first item
                of the iterable will be used as the starting point.

        Returns:
            Any: The reduced value obtained after applying the function to the iterable.
        """
        if initializer is not None:
            return _reduce(fn, self._it, initializer)
        return _reduce(fn, self._it)

    def for_each(self, fn):
        """
        Applies the given function to each item in the iterable.

        This method iterates over all items in the internal iterable and applies the
        provided function to each item. The function provided as an argument must
        be callable.

        Args:
            fn (Callable): A callable function that takes a single argument,
                representing an item from the iterable, and performs an operation
                on it.

        Returns:
            None
        """
        for x in self._it:
            fn(x)
        # Java's forEach returns void; in Python, return None for clarity

    # Extra pythonic/fat-and-sassy features:
    def to_dict(self, key_fn, value_fn=lambda x: x):
        """
        Converts the items in a collection to a dictionary based on the provided key and value
        functions.

        This method allows transforming the elements of a collection into a dictionary
        structure by applying a key function and an optional value function.

        Args:
            key_fn: A callable that takes an item and returns its corresponding key in the
                resulting dictionary.
            value_fn: A callable that takes an item and returns its corresponding value in the
                resulting dictionary. Defaults to the identity function.

        Returns:
            dict: A dictionary with keys and values generated from applying the respective
                functions to each item in the collection.
        """
        return {key_fn(x): value_fn(x) for x in self._it}

    def group_by(self, key_fn):
        """
        Groups elements of the internal iterable into a dictionary based on a specified key function.

        This method takes a key function as an argument, sorts the internal iterable based on the key
        produced by that function, and then groups the elements of the iterable accordingly. The grouped
        elements are returned as a dictionary where the keys are the unique output of the key function,
        and the values are lists of elements that correspond to each key.

        Args:
            key_fn (Callable): A function that computes a key value for each element in the iterable.

        Returns:
            dict: A dictionary where each key is a unique value returned by the key function, and the value
            is a list of elements that correspond to that key.
        """
        sorted_it = sorted(self._it, key=key_fn)
        return {k: list(g) for k, g in groupby(sorted_it, key_fn)}

    def partition_by(self, pred):
        """
        Divides the elements of the iterable into two groups based on a predicate.

        This method creates two partitions of the elements in the iterable: one group
        contains elements for which the predicate returns True, and the other group
        contains elements for which the predicate returns False.

        Args:
            pred (Callable[[Any], bool]): A predicate function that determines the group
                placement of each element. It takes one argument (an element from the
                iterable) and returns a boolean.

        Returns:
            Dict[bool, List[Any]]: A dictionary with two keys, True and False. The value
                associated with the True key is a list of elements for which the predicate
                returned True, and the value associated with the False key is a list of
                elements for which the predicate returned False.
        """
        t1, t2 = tee(self._it)
        return {
            True: [x for x in t1 if pred(x)],
            False: [x for x in t2 if not pred(x)]
        }
