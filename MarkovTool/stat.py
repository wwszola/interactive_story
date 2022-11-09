from dataclasses import dataclass, field
from enum import Enum
from typing import Hashable
from collections.abc import Generator

class ChunkType(Enum):
    """Enum class, use this as a pattern for matching"""
    RAW = 0
    REF = 1

@dataclass
class ChunkRaw:
    """dataclass storing raw values in a chunk
    
    Attributes:
    start: int
        step of the first state in a chunk
    data: list[int]
    type_: ChunkType
    """
    start: int
    data: list[int]
    type_: ChunkType = field(default = ChunkType.RAW, init = False)

@dataclass
class ChunkRef:
    """dataclass referencing a ChunkRaw
    
    Attributes:
    start: int
        step of the first state in a chunk
    point_to: ChunkRaw
        chunk of data referenced
    length: int
        how much is referenced
    type_: ChunkType
    """
    start: int
    point_to: ChunkRaw
    length: int
    type_: ChunkType = field(default = ChunkType.REF, init = False)

class Collector:
    """Gathers states emitted by instances

    Static:
    _count: int = 0
        number of all instances created
    _gen_id() -> int
        return new unique id

    Attributes:
    _entries: dict
        nested dictionary recording all states, see put for details
    _is_open: bool = True
        if set to False no entries are accepted 
    _id: int

    Methods:
    __init__(self, *instances)
        calls self.open(*instances)  
    __hash__(self) -> int
        returns self._id
    open(self, *instances)
        start accepting entries and bind self to instances
    close(self)
        stop accepting entries
    _length(self, id: int, backend)
    put(self, desc: Description, id: int, step, state) -> bool
        try to make a new entry
    
    Valid instances:
    Instances bound by passing to __init__ or open,
    must implement method _bind_collector(self, collector)
    Instances should emit their state by calling put
    """
    _count: int = 0
    @staticmethod
    def _gen_id() -> int:
        """return new unique id"""
        id = Collector._count
        Collector._count += 1
        return id

    def __init__(self, *instances):
        """Calls self.open(*instances)  
        
        *instances
            see Valid instances in Collector.__doc__ 
        """
        self._entries: dict[Hashable, dict[Hashable, list[ChunkRef | ChunkRaw]]] = {}
        self._entries['__EMPTY__'] = {}
        self._is_open: bool = True
        self._id = Collector._gen_id()
        self.open(*instances)

    def __hash__(self) -> int:
        """Returns self._id"""
        return self._id

    def open(self, *instances):
        """Start accepting entries and bind to instances
        
        *instances
            see Valid instances in Collector.__doc__ 
        """
        self._is_open = True
        for instance in instances:
            if callable(getattr(instance, "_bind_collector", None)):
                instance._bind_collector(self)
    
    def close(self):
        """Stop accepting entries"""
        self._is_open = False

    def _redirect(self, src: Hashable, dst: Hashable, backend: Hashable) -> bool:
        """copy entries of src as emitted by dst
        
        Parameters:
        src: Hashable
            instance to copy entries from
        dst: Hashable
            instance to put entries into
        """
        group = self._entries.get(backend, None)
        if not group or src not in group:
            return False

        src_tape = group[src]
        dst_tape = group.setdefault(dst, [])
        for chunk in src_tape:
            match chunk.type_:
                case ChunkType.REF:
                    dst_tape.append(chunk)
                case ChunkType.RAW:
                    dst_tape.append(ChunkRef(chunk.start, chunk, len(chunk.data)))
        return True
    
    def length(self, instance: Hashable, backend: Hashable = None) -> int:
        """returns """
        if backend is None:
            backend = '__EMPTY__'

        group = self._entries.get(backend, None)
        if not group:
            return None
        
        tape = group.get(instance, None)
        if not group:
            return None

        last = tape[-1]
        match last.type_:
            case ChunkType.RAW:
                return last.start + len(last.data)
            case ChunkType.RAW:
                return last.start + last.length

    def _retrieve(self, instance: Hashable, step: int, backend: Hashable) -> int:
        group = self._entries.get(backend, None)
        if not group:
            return None
        
        tape = group.get(instance, None)
        if not group:
            return None
        
        for chunk in tape:
            match chunk.type_:
                case ChunkType.RAW:
                    if chunk.start + len(chunk.data) > step:
                        return chunk.data[step - chunk.start]
                case ChunkType.REF:
                    if chunk.start + chunk.length > step:
                        return chunk.point_to.data[step - chunk.start]

        return None

    def _match(self, instance: Hashable, step: int, state: int, backend: Hashable) -> tuple[int, int]:
        group = self._entries.get(backend, None)
        if not group:
            return None
        
        tape = group.get(instance, None)
        if not group:
            return None
        
        for chunk in tape:
            if chunk.type_ == ChunkType.RAW and chunk.start + len(chunk.data) > step:
                return chunk if chunk.data[step - chunk.start] == state else None
        
        return None

    def playback(self, instance: Hashable, backend: Hashable = None) -> Generator:
        if backend is None:
            backend = '__EMPTY__'
        
        group = self._entries.get(backend, None)
        if not group:
            return None

        tape = group.get(instance, None)
        if not tape:
            return None

        for chunk in tape:
            match chunk.type_:
                case ChunkType.RAW:
                    for state in chunk.data:
                        yield state
                case ChunkType.REF:
                    raw = chunk.point_to
                    start = chunk.start - raw.start
                    for state in raw.data[start : start + chunk.length]:
                        yield state
        return None

    def put(self, instance: Hashable, step: int, state: int, backend: Hashable = None) -> bool:
        """Try to make a new entry

        Makes sure no duplicates are present.
        The entry is accepted if self._is_open == True,
        and one of the following is also True:
        - a chunk exists that was started by the same instance,
        and awaits new value at the correct step
        - no value in any chunk exists that could be 
        matched correctly to the entry
        Parameters:
        TODO
        Returns:
        True if the entry has been accepted, False otherwise 
        """
        if not self._is_open:
            return False        

        if backend is None:
            backend = '__EMPTY__'

        group = self._entries.setdefault(backend, dict())
        tape = group.setdefault(instance, [])

        matches = list(filter(
            lambda chunk: chunk is not None,
            [self._match(instance_, step, state, backend) for instance_ in group.keys() if instance != instance_]
        ))
        raw = matches[0] if matches else None

        if not tape:
            if raw:
                tape.append(ChunkRef(step, raw, 1))
            else:
                tape.append(ChunkRaw(step, [state]))
            return True

        last = tape[-1]
        match last.type_, bool(raw):
            case [ChunkType.REF, True]:
                if last.point_to is raw:
                    last.length += 1
            case [ChunkType.RAW, True]:
                tape.append(ChunkRef(step, raw, 1))
            case [ChunkType.REF, False]:
                tape.append(ChunkRaw(step, [state]))
            case [ChunkType.RAW, False]:
                last.data.append(state)
            
        return True