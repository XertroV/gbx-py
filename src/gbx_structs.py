from functools import partial
import datetime
import string

import lzo
import src.mini_lzo
import zlib
import zipfile
import io

from construct import *
from src.my_construct import MyRepeatUntil

from src.gbx_enums import *

GbxCompressedBody = Struct(
    "uncompressed_size" / Int32ul,
    "compressed_body" / Prefixed(Int32ul, GreedyBytes),
)


class CompressedLZ0(Tunnel):
    def _decode(self, raw_bytes, context, path):
        data = GbxCompressedBody.parse(raw_bytes)

        return lzo.decompress(data.compressed_body, False, data.uncompressed_size)

        # return mini_lzo.decompress(data.compressed_body, data.uncompressed_size)

    def _encode(self, raw_bytes, context, path):
        return GbxCompressedBody.build(
            Container(
                uncompressed_size=len(raw_bytes),
                # compressed_body=mini_lzo.compress(raw_bytes),
                compressed_body=lzo.compress(raw_bytes, 9, False),
            )
        )


class ACompressedZip(Adapter):
    def _decode(self, raw_bytes, context, path):
        self.buffer = io.BytesIO(raw_bytes)
        return zipfile.ZipFile(self.buffer, "a", compression=zipfile.ZIP_DEFLATED)

    def _encode(self, zip, context, path):
        return self.buffer.getvalue()


GbxCompressedZip = ACompressedZip(Prefixed(Int32ul, GreedyBytes))

import zlib

ini_data = None


class CompressedZlib2(Tunnel):
    def __init__(self, subcon):
        super().__init__(subcon)

    def _decode(self, data, context, path):
        global ini_data
        un = zlib.decompress(data)
        ini_data = un
        return un

    def _encode(self, data, context, path):
        from deep_compare import CompareVariables

        print(len(ini_data))
        print(len(data))

        with open("bytes1.txt", "wb") as f:
            f.write(ini_data)
        with open("bytes2.txt", "wb") as f:
            f.write(data)

        # for i in range(len(ini_data)):
        #     print(CompareVariables.compare(ini_data[i], data[i]))

        return zlib.compress(data, 9)


# TODO Adapter
# TODO manage rest
def CompressedZLib(subcon):
    return Struct(
        "uncompressedSize" / Int32ul,
        "content" / Prefixed(Int32ul, Compressed(subcon, "zlib", level=9)),
        # "content" / Prefixed(Int32ul, CompressedZlib2(subcon)),
        # "content" / Prefixed(Int32ul, GreedyBytes),
    )


def CompressedZLibBytes(subcon):
    return Struct(
        "uncompressedSize" / Int32ul,
        "content" / Prefixed(Int32ul, GreedyBytes),
    )


class EndWithFACADE01(Tunnel):
    def _decode(self, raw_bytes, context, path):
        if Int32ul.parse(raw_bytes[-4:]) != 0xFACADE01:
            print(" -- might be corrupted -- ")
        return raw_bytes

    def _encode(self, raw_bytes, context, path):
        return raw_bytes


GbxChunkId = Hex(Int32ul)

GbxString = PascalString(Int32ul, "utf-8")


def check_bool(obj, ctx):
    if obj == 0x01:
        return True
    if obj == 0x00:
        return False
    print("Not a bool!" + str(hex(obj)))
    return False


GbxBool = ExprAdapter(
    Int32ul,
    decoder=check_bool,
    encoder=lambda obj, ctx: 0x01 if obj else 0x00,
)
GbxBoolByte = ExprAdapter(
    Byte,
    decoder=check_bool,
    encoder=lambda obj, ctx: 0x01 if obj else 0x00,
)

GbxFloat = Float32l

GbxVec2 = Struct("x" / GbxFloat, "y" / GbxFloat)
GbxVec3 = Struct("x" / GbxFloat, "y" / GbxFloat, "z" / GbxFloat)
GbxVec3Byte = Struct("x" / Byte, "y" / Byte, "z" / Byte)
GbxVec4 = Struct("x" / GbxFloat, "y" / GbxFloat, "z" / GbxFloat, "w" / GbxFloat)
GbxQuat = GbxVec4
GbxTexPos = Struct("x" / Int16ul, "y" / Int16ul)
GbxInt2 = Struct("x" / Int32sl, "y" / Int32sl)
GbxInt3 = Struct("x" / Int32sl, "y" / Int32sl, "z" / Int32sl)
GbxInt3Byte = Struct("x" / Int8ul, "y" / Int8ul, "z" / Int8ul)
GbxPose3D = Struct(
    "x" / GbxFloat,
    "y" / GbxFloat,
    "z" / GbxFloat,
    "yaw" / GbxFloat,
    "pitch" / GbxFloat,
    "roll" / GbxFloat,
)
GbxLoc = Struct("pos" / GbxVec3, "rot" / GbxQuat)
GbxBox = Struct(
    "x1" / GbxFloat,
    "y1" / GbxFloat,
    "z1" / GbxFloat,
    "x2" / GbxFloat,
    "y2" / GbxFloat,
    "z2" / GbxFloat,
)
GbxBoxInt = Struct(
    "x1" / Int32sl,
    "y1" / Int32sl,
    "z1" / Int32sl,
    "x2" / Int32sl,
    "y2" / Int32sl,
    "z2" / Int32sl,
)
GbxColor = Struct("b" / Byte, "g" / Byte, "r" / Byte, "a" / Byte)
GbxPlugSurfaceMaterialId = Struct(
    "physicsId" / GbxEPlugSurfacePhysicsId,
    "gameplayId" / GbxEPlugSurfaceGameplayId,
)

GbxBytesUntilFacade = Struct(
    "bytes_until_facade"
    / IfThenElse(
        lambda this: this._building,
        GreedyBytes,
        ExprAdapter(
            RepeatUntil(lambda x, lst, ctx: lst[-4:] == [0x01, 0xDE, 0xCA, 0xFA], Byte),
            lambda obj, ctx: bytes(obj[:-4]),
            lambda obj, ctx: GreedyBytes.build(obj + b"\x01\xDE\xCA\xFA"),
        ),
    ),
    Seek(-4, 1),
)


def tenb_to_float(x):
    if x >= 0x201:
        x -= 0x400
    return x / 0x1FF


def float_to_tenb(x):
    x = min(max(x, -1), 1)
    x = int(x * 0x1FF)
    if x < 0:
        x += 0x400
    return x


class AGbxDec3N(Adapter):
    def _decode(self, obj, ctx, path):
        return Container(
            x=tenb_to_float(obj & 0x3FF),
            y=tenb_to_float((obj >> 10) & 0x3FF),
            z=tenb_to_float((obj >> 20) & 0x3FF),
        )

    def _encode(self, obj, ctx, path):
        return float_to_tenb(obj.x) + (float_to_tenb(obj.y) << 10) + (float_to_tenb(obj.z) << 20)


GbxDec3N = AGbxDec3N(Int32ul)


class AGbxUDec4N(Adapter):
    def _decode(self, obj, ctx, path):
        return Container(
            x=((obj >> 0x10) & 0xFF) * 0.003921569,
            y=((obj >> 0x08) & 0xFF) * 0.003921569,
            z=((obj >> 0x00) & 0xFF) * 0.003921569,
            w=((obj >> 0x18) & 0xFF) * 0.003921569,
        )

    def _encode(self, obj, ctx, path):
        return (
            ((round(obj.x * 255.0) & 0xFF) << 0x10)
            + ((round(obj.y * 255.0) & 0xFF) << 0x08)
            + ((round(obj.z * 255.0) & 0xFF) << 0x00)
            + ((round(obj.w * 255.0) & 0xFF) << 0x18)
        )


GbxUDec4N = AGbxUDec4N(Int32ul)


def GbxDict(key, value):
    return PrefixedArray(Int32ul, Struct("key" / key, "value" / value))


GbxDictString = GbxDict(GbxString, GbxString)


GbxMat3x3 = Struct(
    "XX" / GbxFloat,
    "XY" / GbxFloat,
    "XZ" / GbxFloat,
    "YX" / GbxFloat,
    "YY" / GbxFloat,
    "YZ" / GbxFloat,
    "ZX" / GbxFloat,
    "ZY" / GbxFloat,
    "ZZ" / GbxFloat,
)
GbxIso4 = Struct(
    "XX" / GbxFloat,
    "XY" / GbxFloat,
    "XZ" / GbxFloat,
    "YX" / GbxFloat,
    "YY" / GbxFloat,
    "YZ" / GbxFloat,
    "ZX" / GbxFloat,
    "ZY" / GbxFloat,
    "ZZ" / GbxFloat,
    "TX" / GbxFloat,
    "TY" / GbxFloat,
    "TZ" / GbxFloat,
)

GbxInt3 = Struct("x" / Int32sl, "y" / Int32sl, "z" / Int32sl)


class AGbxFileTime(Adapter):
    EPOCH_START = datetime.datetime(1601, 1, 1)

    def _decode(self, file_time, context, path):
        delta = datetime.timedelta(microseconds=file_time / 10)
        try:
            date_time = self.EPOCH_START + delta
            return date_time
        except:
            return file_time

    def _encode(self, date_time, context, path):
        time_delta = date_time - self.EPOCH_START
        return int(time_delta / datetime.timedelta(microseconds=1)) * 10


GbxFileTime = AGbxFileTime(Int64ul)

GbxFileRef = Struct(
    "version" / Int8ul,  # 3
    "checksum" / Bytes(32),
    "filePath" / GbxString,
    "locatorUrl" / GbxString,
)

GbxCollectionIds = {
    0: "Desert Speed",
    1: "Snow Alpine",
    3: "Island",
    4: "Bay",
    7: "Basic",
    11: "Valley",
    26: "Stadium2020",
    10003: "PlayerModels2020",
}
GbxCollectionIdsFromStr = {v: k for k, v in GbxCollectionIds.items()}


GbxFolders = Struct(
    "name" / GbxString,
    "folders" / LazyBound(lambda: PrefixedArray(Int32ul, GbxFolders)),
)


def need_version(this):
    if this._root._params.gbx_data["lookbackstring_version"]:
        return False
    else:
        this._root._params.gbx_data["lookbackstring_version"] = True
        return True


def need_string(this):
    flags = this.index >> 30
    idx = this.index & 0x3FFFFFFF
    return idx == 0 and flags != 0


def decode_lookbackstring(obj, ctx):
    gbx_data = ctx._root._params.gbx_data

    flags = obj.index >> 30
    idx = obj.index & 0x3FFFFFFF

    if idx == 0x3FFFFFFF:
        if flags == 2:
            return "Unassigned"
        elif flags == 3:
            return ""
    elif flags == 0:
        if idx not in GbxCollectionIds:
            s = f"<Unknown collection id: {idx}>"
            print(s)
            return s
        return GbxCollectionIds[idx]
    elif idx == 0:
        # new string
        gbx_data["lookbackstring_index"] += 1
        gbx_data["lookbackstring_table"][gbx_data["lookbackstring_index"]] = obj.string
        return obj.string
    elif idx in gbx_data["lookbackstring_table"]:
        # known string
        return gbx_data["lookbackstring_table"][idx]
    else:
        s = f"<INVALID IDX: {idx}>"
        print(s)
        return s


def encode_lookbackstring(obj, ctx):
    gbx_data = ctx._root._params.gbx_data
    idx = 0x40000000

    if obj == "Unassigned":
        idx = 0xBFFFFFFF
    elif obj == "":
        idx = 0xFFFFFFFF
    elif obj in GbxCollectionIdsFromStr:
        idx = GbxCollectionIdsFromStr[obj]
    elif obj in gbx_data["lookbackstring_table"]:
        # known string
        idx = 0x40000000 | gbx_data["lookbackstring_table"][obj]
    else:
        # new string
        gbx_data["lookbackstring_index"] += 1
        gbx_data["lookbackstring_table"][obj] = gbx_data["lookbackstring_index"]
        idx = 0x40000000

    return Container(version=3, index=idx, string=obj)


class TGbxLookbackString(str):
    pass


GbxLookbackString = ExprAdapter(
    Struct(
        "version" / If(need_version, ExprValidator(Int32ul, obj_ == 3)),
        "index" / Int32ul,
        "string" / If(need_string, GbxString),
    ),
    lambda *args: TGbxLookbackString(decode_lookbackstring(*args)),
    encode_lookbackstring,
)


class GbxLookbackStringContext(Construct):
    def __init__(self, subcon):
        super().__init__()
        self.subcon = subcon

    def _parse(self, stream, context, path):
        old_table = context._root._params.gbx_data.pop("lookbackstring_table", None)
        old_index = context._root._params.gbx_data.pop("lookbackstring_index", None)
        old_version = context._root._params.gbx_data.pop("lookbackstring_version", None)

        context._root._params.gbx_data["lookbackstring_table"] = {}
        context._root._params.gbx_data["lookbackstring_index"] = 0
        context._root._params.gbx_data["lookbackstring_version"] = False

        res = self.subcon._parse(stream, context, path)

        context._root._params.gbx_data["lookbackstring_table"] = old_table
        context._root._params.gbx_data["lookbackstring_index"] = old_index
        context._root._params.gbx_data["lookbackstring_version"] = old_version

        return res

    def _build(self, obj, stream, context, path):
        old_table = context._root._params.gbx_data.pop("lookbackstring_table", None)
        old_index = context._root._params.gbx_data.pop("lookbackstring_index", None)
        old_version = context._root._params.gbx_data.pop("lookbackstring_version", None)

        context._root._params.gbx_data["lookbackstring_table"] = {}
        context._root._params.gbx_data["lookbackstring_index"] = 0
        context._root._params.gbx_data["lookbackstring_version"] = False

        res = self.subcon._build(obj, stream, context, path)

        context._root._params.gbx_data["lookbackstring_table"] = old_table
        context._root._params.gbx_data["lookbackstring_index"] = old_index
        context._root._params.gbx_data["lookbackstring_version"] = old_version

        return res

    def _sizeof(self, context, path):
        return self.subcon._sizeof(context, path)


GbxMeta = Struct(
    "id" / GbxLookbackString,
    "collection" / GbxLookbackString,
    "author" / GbxLookbackString,
)

GbxEmbeddedFile = Prefixed(Int32ul, GreedyBytes)


class GbxOptimizedInt(Construct):
    def __init__(self, size_func):
        super().__init__()
        self.size_func = size_func

    def get_struct(self, context):
        if callable(self.size_func):
            max_size = self.size_func(context)
        else:
            max_size = self.size_func

        if max_size < 2**8:
            struct = Int8ul
        elif max_size < 2**16:
            struct = Int16ul
        else:
            struct = Int32ul

        return struct

    def _parse(self, stream, context, path):
        struct = self.get_struct(context)

        return struct._parse(stream, context, path)

    def _build(self, obj, stream, context, path):
        struct = self.get_struct(context)

        return struct._build(obj, stream, context, path)

    def _sizeof(self, context, path):
        struct, length = self.get_struct(context)

        return struct._sizeof(context, path)


class GbxOptimizedIntArray(Construct):
    def __init__(self, length_func=None, size_func=None):
        super().__init__()
        self.length_func = length_func
        self.size_func = size_func

    def get_struct(self, context):
        # if self.length_func is None:
        #     length = Int32ul._parse()
        # else:
        assert self.length_func is not None  # TODO

        if callable(self.length_func):
            length = self.length_func(context)
        else:
            length = self.length_func

        if self.size_func is not None and callable(self.size_func):
            max_size = self.size_func(context)
        else:
            max_size = length

        if max_size < 2**8:
            struct = Int8ul
        elif max_size < 2**16:
            struct = Int16ul
        else:
            struct = Int32ul

        return struct, length

    def _parse(self, stream, context, path):
        struct, length = self.get_struct(context)

        return struct[length]._parse(stream, context, path)

    def _build(self, obj, stream, context, path):
        struct, length = self.get_struct(context)

        return struct[length]._build(obj, stream, context, path)

    def _sizeof(self, context, path):
        struct, length = self.get_struct(context)

        return struct._sizeof(context, path) * length


body_chunks = {}

GbxNodesWithoutBody = set(
    [
        0x0912F000,
        0x09144000,
        0x09145000,
        0x09159000,
        0x09178000,
        0x09179000,
        0x0917B000,
        0x09187000,
        0x2F074000,
        0x2F0BC000,
        0x2F086000,
        0x2F0CA000,
    ]
)


def print_next_chunk_id(obj, ctx):
    # print(f"Parsing... {obj}")
    return obj


def print_chunk_unknown(obj, ctx):
    print(f" -- Unknown chunk id: {hex(ctx._.chunkId)}")
    return obj


def print_chunk_fail(obj, ctx):
    print(f" -- Parse chunk failed: {hex(ctx._.chunkId)}")
    return obj


GbxBodyChunks = MyRepeatUntil(
    lambda obj, lst, ctx: obj is None or "rest" in obj or obj.chunkId == 0xFACADE01,
    Select(
        Struct(
            "chunkId" / ExprValidator(GbxChunkId, obj_ == 0xFACADE01),
        ),
        Struct(
            "chunkId" / GbxChunkId,
            "skippable" / ExprValidator(Const(b"PIKS"), obj_ == b"PIKS"),
            "chunk"
            / Prefixed(
                Int32ul,
                Select(
                    Switch(
                        this.chunkId,
                        body_chunks,
                        default=GreedyBytes,
                    ),
                    Struct("_chunkParseFailed" / GreedyBytes * print_chunk_fail),
                ),
            ),
        ),
        Struct(
            "chunkId" / GbxChunkId,
            "chunk"
            / Switch(
                this.chunkId,
                body_chunks,
                default=Struct("_unknownChunkId" / GbxBytesUntilFacade * print_chunk_unknown),
            ),
        ),
        Struct(
            "chunkId" / GbxChunkId,
            "chunk" / Struct("_chunkParseFailed" / GreedyBytes * print_chunk_fail),
        ),
        Struct("rest" / GreedyBytes),
    ),
)


def print_chunk_unknown_noderef(obj, ctx):
    print(f" -- Unknown chunk in node ref, id: {hex(ctx._.classId)}")
    return obj


GbxBody = IfThenElse(
    lambda this: this.classId in GbxNodesWithoutBody,
    Switch(
        lambda this: this.classId,
        body_chunks,
        default=Struct("unknown_chunk_in_node_ref" / GreedyBytes * print_chunk_unknown_noderef),
    ),
    GbxBodyChunks
    # EndWithFACADE01(GbxBodyChunks),
)
# TODO GbxClass is GbxNodeRef when encapsulated
GbxClass = Struct(
    "classId" / GbxChunkId,
    "body" / If(lambda this: this.classId != 0xFFFFFFFF, GbxBody),
)


def need_node_body(this):
    if 1 <= this.index < len(this._root._params.nodes):
        if this._parsing:
            return this._root._params.nodes[this.index] is None
        elif this._building:
            return this.internal_node is not None
        else:
            raise Exception(f"Unknwon state")
    else:
        print(f"Unknown node ref index: {this.index}")


class TGbxNodeRef(int):
    pass


def get_noderef_offset(ctx):
    while "_" in ctx:
        ctx = ctx._
        if "node_offset" in ctx:
            return ctx.node_offset
    return 0


class GbxNodeRefAdapter(Adapter):
    def _decode(self, obj, ctx, path):
        if obj.index == -1:
            return TGbxNodeRef(-1)

        # print(f"node_ref {obj.index}")
        if obj.internal_node is not None:
            # print(f"parsed {obj.index} {path}")
            ctx._root._params.nodes[obj.index] = obj.internal_node

        return TGbxNodeRef(obj.index)

    def _encode(self, obj, ctx, path):
        # print(obj)
        if obj == -1:
            return Container(index=-1)
        # elif type(obj) == int:
        #     print(f"reuse {obj}")
        #     return obj

        # print(f"node ref {obj} + {get_noderef_offset(ctx)} => {obj + get_noderef_offset(ctx)}")
        obj += get_noderef_offset(ctx)

        internal_node = None
        if ctx._root._params.nodes[obj] is not None:
            internal_node = ctx._root._params.nodes[obj]
            ctx._root._params.nodes[obj] = None

        return Container(index=obj, internal_node=internal_node)


GbxNodeRef = GbxNodeRefAdapter(
    Struct(
        "index" / Int32sl,
        StopIf(this.index == -1),
        "internal_node"
        / If(
            need_node_body,
            Struct("classId" / GbxChunkId, "body" / GbxBody),
        ),
    ),
)

GbxMaterial = Struct(
    "material_name" / GbxString,
    "material_user_inst" / If(lambda this: len(this.material_name) == 0, GbxNodeRef),
)


# Body Chunks

# 0301B CGameCtnCollectorList
body_chunks[0x0301B000] = Struct(
    "collectorStock"
    / PrefixedArray(
        Int32ul,
        Struct(
            "ident" / GbxMeta,
            "count" / Int32ul,
        ),
    ),
)

# 03036 CGameCtnBlockUnitInfo
body_chunks[0x03036000] = Struct(
    "placePylons" / Int32sl,
    "u01" / GbxBool,  # AcceptPylons?
    "u02" / GbxBool,
    "relativeOffset" / GbxInt3,
    "clips" / PrefixedArray(Int32ul, GbxNodeRef),  # pylons clips?
)
body_chunks[0x03036001] = Struct(
    "u01" / GbxNodeRef,  # Desert, Grass
    "u02" / Int32sl,
    "u03" / Int32sl,
)
body_chunks[0x03036002] = Struct(
    "u01" / GbxBytesUntilFacade,  # Bytes(12),  # undergound?
)
body_chunks[0x03036004] = Struct(
    "u01" / Int32sl,
)
body_chunks[0x03036005] = Struct(
    "terrainModifierId" / GbxNodeRef,
)
body_chunks[0x03036007] = Struct(
    "u01" / GbxNodeRef[4],
)
body_chunks[0x0303600C] = Struct(
    "version" / Int32ul,
    "countClips"
    / ByteSwapped(  # little endian 32 bit
        BitStruct(
            Padding(14),
            "Bottom" / BitsInteger(3),
            "Top" / BitsInteger(3),
            "West" / BitsInteger(3),
            "South" / BitsInteger(3),
            "East" / BitsInteger(3),
            "North" / BitsInteger(3),
        )
    ),
    "clipsNorth" / Array(this.countClips.North, GbxNodeRef),  # CGameCtnBlockInfoClip
    "clipsEast" / Array(this.countClips.East, GbxNodeRef),  # CGameCtnBlockInfoClip
    "clipsSouth" / Array(this.countClips.South, GbxNodeRef),  # CGameCtnBlockInfoClip
    "clipsWest" / Array(this.countClips.West, GbxNodeRef),  # CGameCtnBlockInfoClip
    "clipsTop" / Array(this.countClips.Top, GbxNodeRef),  # CGameCtnBlockInfoClip
    "clipsBottom" / Array(this.countClips.Bottom, GbxNodeRef),  # CGameCtnBlockInfoClip
    "u01" / Int16sl,
    "u02" / Int16sl,
)

# 0303F CGameGhost

body_chunks[0x0303F005] = Struct("data" / CompressedZLib(GreedyBytes))
body_chunks[0x0303F006] = Struct(
    "isReplaying" / GbxBool,
    *body_chunks[0x0303F005].subcons,
)
body_chunks[0x0309200C] = Struct("u01" / Int32sl)
body_chunks[0x0309200E] = Struct("ghostUid" / Int32sl)
body_chunks[0x0309200F] = Struct("ghostLogin" / GbxString)
body_chunks[0x03092010] = Struct("validate_ChallengeUid" / GbxLookbackString)
body_chunks[0x0309201C] = Struct("u01" / Bytes(32))  # BigInt?

# 03043 CGameCtnChallenge

GbxBlockInstance = Struct(
    "name" / GbxLookbackString,
    "dir" / GbxECardinalDir,
    "coords" / GbxInt3Byte,
    "flags"
    / Select(
        ExprValidator(Int32sl, obj_ == -1),
        ByteSwapped(
            BitStruct(
                "u04" / BitsInteger(2),  # 30-31
                "isFree" / Flag,  # 29
                "isGhost" / Flag,  # 28
                "blockVariantIndex" / BitsInteger(7),  # 21-27
                "isWaypoint" / Flag,  # 20
                "hasU05" / Flag,  # 19
                "hasObsolete0" / Flag,  # 18
                "hasU06" / Flag,  # 17
                "u02a" / Flag,  # 16
                "isSkinnable" / Flag,  # 15
                "u01" / Flag,  # 14
                "isClip" / Flag,  # 13
                "isGround" / Flag,  # 12
                "mobilVariantIndex" / BitsInteger(6),  # 6-11
                "mobilIndex" / BitsInteger(6),  # 0-5
            )
        ),
    ),
    StopIf(this.flags == -1),
    "skinParams"
    / If(
        this.flags.isSkinnable,
        Struct(
            "author" / GbxLookbackString,
            "skin" / GbxNodeRef,  # 0x3059000
        ),
    ),
    "u05" / If(this.flags.hasU05, GbxNodeRef),  # CPlugCharPhySpecialProperty
    "waypointParams" / If(this.flags.isWaypoint, GbxNodeRef),  # CGameWaypointSpecialProperty
    "obsolete0" / If(this.flags.hasObsolete0, Pass),  # obsolete, list of vec3?
    "u06"
    / If(
        this.flags.hasU06,
        Struct(
            "u01" / GbxLookbackString,  # -1?
            "u02" / Int32sl,
            "u03" / Int32sl,
        ),
    ),
    # TODO what's this?
    # coord -= (1, 0, 1); if version >= 6
    # coord -= (0, 1, 0); if free block
    # "unassigned1BlockParams"
    # / Select(
    #     Struct(
    #         ExprValidator(Peek(Int32ul), lambda obj, ctx: obj & 0xC0000000 > 0),
    #         "name" / ExprValidator(GbxLookbackString, obj_ == "Unassigned1"),
    #         "dir" / GbxECardinalDir,
    #         "coords" / GbxInt3Byte,
    #         "flags" / ExprValidator(Int32sl, obj_ == -1),
    #     ),
    #     Pass,
    # ),
)


def countBlocks(block, lst, ctx):
    if "_nbBlocks" not in ctx:
        ctx._nbBlocks = 0
    if block.flags != -1:
        ctx._nbBlocks += 1
    return ctx.nbBlocks <= ctx._nbBlocks
    # and ((r.PeekUInt32() & 0xC0000000) > 0)


def GbxBlockInstances(name):
    return Struct(
        "nbBlocks" / Int32ul,  # TODO recompute ctx["_nbBlocks"]
        name / RepeatUntil(countBlocks, GbxBlockInstance),
    )


body_chunks[0x0304300D] = Struct(
    "playerModel" / GbxMeta,
)
body_chunks[0x03043011] = Struct(
    "blockStock" / GbxNodeRef,  # CGameCtnCollectorList
    "challengeParameters" / GbxNodeRef,  # CGameCtnChallengeParameters
    "kind" / GbxEMapKind,
)
body_chunks[0x0304301F] = Struct(
    "mapInfo" / GbxMeta,
    "mapName" / GbxString,
    "decoration" / GbxMeta,
    "size" / GbxInt3,
    "needUnlock" / GbxBool,
    "version" / Int32ul,  # 6, only if not 03043013
    "blocks" / PrefixedArray(Int32ul, GbxBlockInstance),
)
body_chunks[0x03043022] = Struct(
    "u01" / Int32sl,
)
body_chunks[0x03043024] = Struct(
    "customMusicPackDesc" / GbxFileRef,
)
body_chunks[0x03043025] = Struct(
    "mapCoordOrigin" / GbxVec2,
    "mapCoordTarget" / GbxVec2,
)
body_chunks[0x03043026] = Struct(
    "clipGlobal" / GbxNodeRef,
)
body_chunks[0x03043027] = Struct(
    "hasCustomCamThumbnail" / GbxBool,
    "customCamThumbnail"
    / If(
        this.hasCustomCamThumbnail,
        Struct(
            "u01" / Byte,
            "u02" / GbxVec3,
            "u03" / GbxVec3,
            "u04" / GbxVec3,
            "thumbnailPosition" / GbxVec3,
            "thumbnailFOV" / GbxFloat,
            "thumbnailNearClipPlane" / GbxFloat,
            "thumbnailFarClipPlane" / GbxFloat,
        ),
    ),
)
body_chunks[0x03043028] = Struct(
    *body_chunks[0x03043027].subcons,
    "comments" / GbxString,
)
body_chunks[0x03043029] = Struct(
    "passwordHash" / Hex(BytesInteger(16, swapped=True)),
    "crc32" / Int32ul,  # CRC32("0x" + uppercase(hex(passwordHash)) + "???" + mapId) TODO autocompute
)
body_chunks[0x0304302A] = Struct(
    "u01" / GbxBool,
)
body_chunks[0x03043040] = GbxLookbackStringContext(
    Struct(
        "version" / Int32ul,  # 7
        "u01" / Int32sl,
        "size" / Int32sl,
        "_listVersion" / Int32ul,
        "anchoredObjects" / PrefixedArray(Int32ul, GbxClass),
        "itemsOnItem"
        / If(
            lambda this: this.version >= 1 and this.version != 5,
            PrefixedArray(Int32ul, GbxInt2),
        ),
        StopIf(this.version < 5),
        "blockIndexes" / PrefixedArray(Int32ul, Int32sl),
        "snapItemGroups" / If(this.version < 7, PrefixedArray(Int32ul, Int32sl)),
        "itemIndexes" / If(this.version >= 6, PrefixedArray(Int32ul, Int32sl)),
        "snapItemGroups" / If(this.version >= 7, PrefixedArray(Int32ul, Int32sl)),
        "u07" / If(this.version != 6, PrefixedArray(Int32ul, Int32sl)),
        "snappedIndexes" / PrefixedArray(Int32ul, Int32sl),
    )
)
body_chunks[0x03043048] = Struct(
    "version" / Int32ul,
    "listBlocksVersion" / Int32ul,
    *GbxBlockInstances("BakedBlocks").subcons,
    "rest" / GreedyBytes,
    # "u02" / Int32sl,
    # "BakedClipsAdditionalData"
    # / PrefixedArray(
    #     Int32ul,
    #     Struct(
    #         "Clip1" / GbxMeta,
    #         "Clip2" / GbxMeta,
    #         "Clip3" / GbxMeta,
    #         "Clip4" / GbxMeta,
    #         "Coord" / GbxInt3Byte,
    #     ),
    # ),
)
body_chunks[0x03043049] = Struct(
    "bytes_until_0x0304304B"
    / IfThenElse(
        lambda this: this._building,
        GreedyBytes,
        ExprAdapter(
            RepeatUntil(lambda x, lst, ctx: lst[-4:] == [0x4B, 0x30, 0x04, 0x03], Byte),
            lambda obj, ctx: bytes(obj[:-4]),
            lambda obj, ctx: GreedyBytes.build(obj + b"\x4B\x30\x04\x03"),
        ),
    ),
    Seek(-4, 1),
)
# = Struct(
#     "version" / Int32ul,
#     "clipIntro" / GbxNodeRef,  # CGameCtnMediaClip
#     "clipPodium" / GbxNodeRef,  # CGameCtnMediaClip
#     "clipGroupInGame" / GbxNodeRef,  # CGameCtnMediaClipGroup
#     "clipGroupEndRace" / GbxNodeRef,  # CGameCtnMediaClipGroup
#     "clipAmbiance" / GbxNodeRef,  # CGameCtnMediaClip
#     "triggerSize" / GbxInt3,  # dividor
# )

SHmsLightMapCacheSmall = Struct(
    "version" / Int32ul,  # 8
    "lightmapFrames"
    / PrefixedArray(
        Int32ul,
        Struct(
            "frame1" / GbxEmbeddedFile,
            "frame2" / GbxEmbeddedFile,
            "frame3" / GbxEmbeddedFile,
        ),
    ),
    # TODO if lightmapFrames > 0
    "data"
    / If(
        lambda this: len(this.lightmapFrames) > 0,
        CompressedZLib(
            Struct(
                "body" / GbxLookbackStringContext(GbxBodyChunks),
                "rest" / GreedyBytes,
            )
        ),
    ),
)
body_chunks[0x03043054] = Struct(  # embedded objects
    "version" / Int32ul,
    "u01" / Int32sl,
    "embeddedData"
    / Prefixed(
        Int32ul,
        GbxLookbackStringContext(
            Struct(
                "filesMeta" / PrefixedArray(Int32ul, GbxMeta),
                "zip" / GbxCompressedZip,
                "Textures" / PrefixedArray(Int32ul, GbxString),
            )
        ),
    ),
)
body_chunks[0x0304305B] = Struct(
    "version" / Int32ul,
    "u01" / GbxBool,
    "u02" / GbxBool,
    "u03" / GbxBool,
    StopIf(lambda this: not this.u01),
    "lightmaps" / SHmsLightMapCacheSmall,
)
body_chunks[0x0304305F] = Struct(
    "version" / Int32ul,  # 0
    "freeBlocks" / GreedyRange(Struct("pos" / GbxVec3, "rotPitchYawRoll" / GbxVec3)),
)


# 0304E CGameCtnBlockInfo
body_chunks[0x0304E00F] = Struct(
    "no_respawn" / GbxBool,
)
body_chunks[0x0304E013] = Struct(
    "icon_auto_use_ground" / GbxBool,
)
body_chunks[0x0304E017] = Struct(
    "u01" / GbxBool,
)
body_chunks[0x0304E020] = Struct(
    "version" / Int32ul,
    "char_phy_special_property" / GbxNodeRef,
    "u01" / If(this.version < 7, GbxNodeRef),
    StopIf(this.version < 2),
    "podium_info" / GbxNodeRef,  # CGamePodiumInfo
    StopIf(this.version < 3),
    "intro_info" / GbxNodeRef,  # CGamePodiumInfo
    StopIf(this.version < 4),
    "char_phy_special_property_customizable" / GbxBool,
    "u02" / If(this.version == 5, GbxBool),
    StopIf(this.version < 8),
    "u03" / GbxBool,
    "u04" / If(this.u03, Struct("u01" / GbxString, "u02" / GbxString)),
)
body_chunks[0x0304E023] = Struct(
    "variant_base_ground" / GbxBodyChunks,
    "variant_base_air" / GbxBodyChunks,
)
body_chunks[0x0304E026] = Struct("wayPointType" / GbxEWayPointType)
body_chunks[0x0304E027] = Struct(
    "listVersion" / ExprValidator(Int32ul, obj_ == 10),
    "additionalVariantsGround" / PrefixedArray(Int32ul, GbxNodeRef),  # CGameCtnBlockInfoVariantGround
)
body_chunks[0x0304E028] = Struct(
    "symmetricalBlockInfoId" / GbxLookbackString,
    "dir" / GbxEDirection,
)
body_chunks[0x0304E029] = Struct(
    "fogVolumeBox" / GbxNodeRef,  # CPlugFogVolumeBox
)
body_chunks[0x0304E02A] = Struct(
    "version" / Int32ul,
    "sound1" / GbxNodeRef,
    "sound2" / GbxNodeRef,
    "sound1Loc" / If(lambda this: this.version < 3 or this.sound1 > 0, GbxIso4),
    "sound2Loc" / If(lambda this: this.version < 3 or this.sound2 > 0, GbxIso4),
)
body_chunks[0x0304E02B] = Struct(
    "version" / Int32ul,
    "u01" / Int32sl,
)
body_chunks[0x0304E02C] = Struct(
    "version" / Int32ul,
    "additionalVariantsAir" / PrefixedArray(Int32ul, GbxNodeRef),  # CGameCtnBlockInfoVariantAir
)
body_chunks[0x0304E02F] = Struct(
    "version" / Int32ul,
    "isPillar" / GbxBoolByte,
    "pillarShapeMultiDir" / GbxEMultiDirByte,
    StopIf(this.version < 1),
    "u01" / Byte,
)
body_chunks[0x0304E031] = Struct(
    "rest" / GbxBytesUntilFacade,
)

# 03059 CGameCtnBlockSkin

body_chunks[0x03059000] = Struct("text" / GbxString, "u01" / GbxString)
body_chunks[0x03059001] = Struct("text" / GbxString, "packDesc" / GbxFileRef)
body_chunks[0x03059002] = Struct(
    "text" / GbxString,
    "packDesc" / GbxFileRef,
    "parentPackDesc" / GbxFileRef,
)
body_chunks[0x03059003] = Struct(
    "version" / Int32ul,
    "foregroundPackDesc" / GbxFileRef,
)

# 0305B CGameCtnChallengeParameters

body_chunks[0x0305B001] = Struct(
    "tip" / GbxString[4],
)
body_chunks[0x0305B004] = Struct(
    "bronzeTime" / Int32sl,  # TODO GbxTimeNullable
    "silverTime" / Int32sl,  # TODO GbxTimeNullable
    "goldTime" / Int32sl,  # TODO GbxTimeNullable
    "authorTime" / Int32sl,  # TODO GbxTimeNullable
    "u01" / Int32sl,
)
body_chunks[0x0305B008] = Struct(
    "timeLimit" / Int32sl,  # TODO GbxTimeNullable
    "authorScore" / Int32sl,
)
body_chunks[0x0305B00D] = Struct(
    "raceValidateGhost" / GbxNodeRef,  # CGameCtnGhost
)

# 03101 CGameCtnAnchoredObject

body_chunks[0x03101002] = Struct(
    "version" / Int32ul,  # 8
    "itemModel" / GbxMeta,
    "rotPitchYawRoll" / GbxVec3,
    "blockUnitCoord" / GbxVec3Byte,
    "anchorTreeId" / GbxLookbackString,
    "absolutePositionInMap" / GbxVec3,
    "waypointSpecialProperty" / GbxClass,
    "u03" / If(this.version < 5, Int32sl),
    StopIf(this.version < 4),
    "flags" / Int16ul,
    StopIf(this.version < 5),
    "pivotPosition" / GbxVec3,
    StopIf(this.version < 6),
    "scale" / GbxFloat,
    StopIf(this.version < 7),
    "packDesc" / If(lambda this: (this.flags & 4) == 4, GbxFileRef),
    StopIf(this.version < 8),
    "u01" / GbxVec3,
    "u02" / GbxVec3,
)

# 0311D CGameCtnZoneGenealogy

body_chunks[0x0311D002] = Struct(
    "zoneIds" / PrefixedArray(Int32ul, GbxLookbackString),
    "currentIndex" / Int32ul,
    "dir" / GbxEDirection,
    "currentZoneId" / GbxLookbackString,
)

# 03120 CGameCtnAutoTerrain
body_chunks[0x03120001] = Struct(
    "offset" / GbxInt3,
    "genealogy" / GbxNodeRef,  # CGameCtnZoneGenealogy
)

# 03122 CGameCtnBlockInfoMobil
body_chunks[0x03122002] = Struct(
    "version" / Int32ul,
    "solid_decals"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / Int32sl,
            "rest" / GreedyBytes,
        ),
    ),
    "u01" / Int32ul,
)
body_chunks[0x03122003] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 12),  # 23
    "u03" / Int32sl,
    StopIf(this.version < 1),
    "hasGeomTransformation" / GbxBoolByte,
    "geomTransformation"
    / If(
        this.hasGeomTransformation,
        Struct("translation" / GbxVec3, "rotation" / GbxVec3),
    ),
    StopIf(this.version < 2),
    "solid_fid" / GbxNodeRef,
    "u14" / If(this.version >= 14, GbxNodeRef),  # CPlugSolid
    StopIf(this.version < 3),
    "prefab_fid" / GbxNodeRef,  # CPlugPrefab
    StopIf(this.version < 4),
    "u12" / GbxNodeRef,
    StopIf(this.version < 6),
    "u13" / GbxNodeRef,
    StopIf(this.version < 7),
    "u15" / GbxNodeRef,
    StopIf(this.version < 9),
    "u16" / Int32sl,  # count?
    StopIf(this.version < 16),
    "u17" / Int32sl,  # count?
    StopIf(this.version < 17),
    "u18" / GbxNodeRef,
    StopIf(this.version < 18),
    "u19" / Bytes(29),
    "u27" / PrefixedArray(Int32ul, GbxNodeRef),
    "u28" / Int32sl,
)
body_chunks[0x03122004] = Struct(
    "version" / Int32ul,
    "list_version" / ExprValidator(Int32sl, obj_ == 10),
    "dyna_links" / PrefixedArray(Int32ul, GbxNodeRef),  # CGameCtnBlockInfoMobilLink
)

# 0315B CGameCtnBlockInfoVariant
body_chunks[0x0315B002] = Struct("multi_dir" / GbxEMultiDir)
body_chunks[0x0315B003] = Struct(
    "version" / Int32ul,
    "symmetrical_variant_index" / Int32sl,
    "cardinal_dir" / If(this.version == 0, Int32ul),
    StopIf(this.version < 1),
    "cardinal_dir" / GbxECardinalDir,
    "variant_base_type" / GbxEVariantBaseType,
    StopIf(this.version < 2),
    "no_pillar_below_index" / Int8sl,
)
body_chunks[0x0315B004] = Struct("u01" / Int16sl)
body_chunks[0x0315B005] = Struct(
    "version" / Int32ul,  # 3
    "mobils" / PrefixedArray(Int32ul, PrefixedArray(Int32ul, GbxNodeRef)),  # CGameCtnBlockInfoMobil
    StopIf(this.version < 2),
    "u02" / Int32sl,
    "u03" / Int32sl,
    StopIf(this.version < 3),
    "u04" / Int32sl,
)
body_chunks[0x0315B006] = Struct(
    "version" / Int32ul,
    "u01" / If(this.version < 9, GbxNodeRef),
    "screenInteractionTriggerSolid" / GbxNodeRef,
    "waypointTriggerSolid" / GbxNodeRef,
    "u04" / If(this.version >= 11, GbxNodeRef),
    "u05" / If(this.version >= 11, GbxNodeRef),
    "u02" / If(this.version < 9, Int32sl),
    StopIf(this.version < 2),
    "gate" / GbxNodeRef,  # CGameGateModel
    StopIf(this.version < 3),
    "teleporter" / GbxNodeRef,  # CGameTeleporterModel
    StopIf(this.version < 5),
    "u03" / GbxNodeRef,
    StopIf(this.version < 6),
    "turbine" / GbxNodeRef,  # CGameTurbineModel
    StopIf(this.version < 7),
    "flockModel" / GbxNodeRef,  # CPlugFlockModel
    "flockEmmiter" / If(this.flockModel > 0, PrefixedArray(Int32ul, Struct("TODO" / GreedyBytes))),
    StopIf(this.version < 8),
    "spawnModel" / GbxNodeRef,  # CGameSpawnModel
    StopIf(this.version < 10),
    "entitySpawners" / PrefixedArray(Int32ul, GbxNodeRef),  # CPlugEntitySpawner
)
body_chunks[0x0315B007] = Struct(
    "version" / Int32ul,
    "probe" / GbxNodeRef,  # CPlugProbe
)
body_chunks[0x0315B008] = Struct(
    "version" / Int32ul,
    "blockUnitModels" / PrefixedArray(Int32ul, GbxNodeRef),  # CGameCtnBlockUnitInfo
    "u01" / Int32sl,
    "hasManualSymmetryH" / GbxBool,
    "hasManualSymmetryV" / GbxBool,
    "hasManualSymmetryD1" / GbxBool,
    "hasManualSymmetryD2" / GbxBool,
    "spawn"
    / IfThenElse(
        this.version < 2,
        Struct("spawnTrans" / GbxVec3, "spawnYaw" / GbxVec3, "spawnPitch" / GbxVec3),
        Struct(
            "spawnTrans" / GbxVec3,
            "u01" / GbxVec3,  # SpawnYaw, SpawnPitch, SpawnRoll
        ),
    ),
    "name" / GbxString,
)
body_chunks[0x0315B009] = Struct(
    "version" / Int32ul,
    "u01"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / GbxNodeRef,
            "u02" / Bytes(16),
        ),
    ),  # PlacedPillarParam
    StopIf(this.version < 1),
    "u02"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / GbxNodeRef,
            "u02" / Bytes(16),
            "u06" / Byte,
        ),
    ),  # ReplacedPillarParam
)
body_chunks[0x0315B00A] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 3),
    "compoundModel" / GbxNodeRef,  # CGameObjectPhyCompoundModel
)
body_chunks[0x0315B00B] = Struct(
    "version" / Int32ul,
    "waterVolumes"
    / PrefixedArray(
        Int32ul,
        Struct(
            "chunks" / PrefixedArray(Int32ul, GbxBoxInt),
            "u01" / Int32sl,
            "chunksSize" / GbxBox,
            "waterType" / GbxLookbackString,
        ),
    ),  # WaterArchive
)
body_chunks[0x0315B00D] = Struct(
    "version" / Int32sl,
    "u01" / Int32sl,
)

# 0315C CGameCtnBlockInfoVariantGround

body_chunks[0x0315C001] = Struct(
    "version" / Int32ul,
    "listVersion" / ExprValidator(Int32ul, obj_ == 10),
    "autoTerrains" / PrefixedArray(Int32ul, GbxNodeRef),  # CGameCtnAutoTerrain
    "autoTerrainHeightOffset" / Int32sl,
    "autoTerrainPlaceType" / GbxEAutoTerrainPlaceType,
)

# 04001 GxLight

body_chunks[0x400100A] = Struct(
    "version" / Int32ul,  # 0
    "u01" / GbxFloat,
    "u02" / GbxFloat,
    "u03" / GbxFloat,
    "u04" / Int32sl,
    "u05" / GbxFloat,
    "u06" / GbxFloat,
    "u07" / GbxFloat,
    "u08" / GbxFloat,
    "u09" / GbxVec3,
)

# 04002 CGxLightBall
# inherits GxLightPoint

body_chunks[0x04002008] = Struct(
    "u01" / Int32sl,
    "u02" / GbxFloat,
    "u03" / GbxFloat,
    "u04" / GbxFloat,
    "u05" / GbxFloat,
    "u06" / GbxFloat,
    "u07" / GbxFloat,
    "u08" / GbxFloat,
    "u09" / GbxFloat,
    "u10" / GbxFloat,
    "u11" / GbxFloat,
    "u12" / GbxFloat,
    "u13" / GbxFloat,
    "u14" / GbxFloat,
)
body_chunks[0x04002009] = Struct(
    "u01" / GbxFloat,
)
body_chunks[0x0400200A] = Struct(
    "u01" / GbxFloat,
)

# 04003 GxLightPoint
# inherits GxLight

body_chunks[0x04003004] = Struct(
    "u01" / GbxFloat,  # FlareSize?
    "u02" / GbxFloat,  # FlareBiasZ?
)

# 0400B CGxLightSpot
# inherits CGxLightBall

body_chunks[0x0400B003] = Struct(
    "version" / Int32ul,  # 1
    "u01" / Int32sl,
    "u02" / GbxFloat,
    "u03" / GbxFloat,
    "u04" / GbxFloat,
    "u05" / GbxFloat,
    "u06" / GbxFloat,
    "u07" / If(this.version >= 1, Int8sl),
    "u08" / If(this.version >= 1, Int8sl),
    "u09" / GbxFloat,
)

# 06022 LightMapCache

body_chunks[0x0602200B] = Struct(
    "mapT3s" / PrefixedArray(Int32ul, Int32sl),
)
body_chunks[0x0602200F] = Struct(
    "quality" / GbxELightMapCacheEQuality,
    "u01" / Int32sl,
)
body_chunks[0x06022013] = Struct(
    "u01" / GbxBool,
    "u02" / GbxBool,
    "u03" / GbxFileTime,
)
body_chunks[0x06022015] = Struct(
    "version" / Int32ul,  # 5
    "u01" / Bytes(8),
    "collection" / GbxLookbackString,
    "decoration" / GbxLookbackString,
    "u02" / Int32sl,
    "u03" / Int32sl,  # 0
    "timeOfDay" / Int32sl,
    "u04" / Int32sl,  # 0
    "u05" / Int32sl,
    "u06" / GbxString,
)
body_chunks[0x06022016] = Struct(
    "version" / GbxELightMapCacheEVersion,
)
body_chunks[0x06022017] = Struct(
    "decal2d" / Int32sl,
    "decal3d" / Int32sl,
)
body_chunks[0x06022018] = Struct(
    "u01" / GbxFileTime,
)
body_chunks[0x06022019] = Struct(
    "qualityVer" / GbxELightMapCacheEQualityVer,
)


def divide_by_four(data, ctx):
    if (data % 4) != 0:
        print("Found a non-multiple of 4")
    return int(data / 4)


def mult_by_four(data, ctx):
    return int(data * 4)


GbxLightMapCacheMapping = Struct(
    "version" / Int32sl,  # 9
    "u01_size" / GbxInt3,
    "u02_lower_bounds" / GbxVec3,
    "u03_upper_bounds" / GbxVec3,
    "u04" / Int32sl,
    "count" / Int32ul,  # meshes
    "data1" / CompressedZLib(GbxFloat[this._.count]),
    "objBindings"
    / CompressedZLib(
        Struct(
            "meshIdx" / Int32ul,
            "objIdx" / ExprAdapter(Int16ul, divide_by_four, mult_by_four),
            "objGroupIdx" / Int16ul,
        )[this._.count]
    ),
    "positions" / CompressedZLib(GbxTexPos[this._.count]),  # position of the mesh uv in lightmap
    "sizes" / CompressedZLib(GbxTexPos[this._.count]),
    "u09" / Int32sl,
    "colorData" / CompressedZLib(PrefixedArray(Int32ul, PrefixedArray(Int32ul, Int8ul))),
    # first one: shadow brightness
)
body_chunks[0x0602201A] = Struct(
    "version" / Int32ul,  # 13
    "countSMap" / Int32ul,
    "u01" / Bytes(this.countSMap * 5 * 4),
    "ambSamples" / Int32sl,  # ambiant light
    "dirSamples" / Int32sl,  # direct light
    "pntSamples" / Int32sl,  # point light / lumière ponctuelle
    "sortMode" / GbxELightMapCacheESortMode,
    "allocMode" / GbxELightMapCacheEAllocMode,
    "u02" / Int32sl,
    "compressMode" / GbxELightMapCacheECompressMode,
    "u03" / Int32sl,
    "bump" / GbxELightMapCacheEBump,
    "maps"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u00" / Int32sl,  # 0
            "ReplayTime" / Int32sl,
            "u01" / Bytes(4),
            "u02" / GbxVec4,
            "u03" / GbxBool,
            "u04" / Float16l[3],  # related to frame2?
            "u05" / GbxBool,
            "u06" / Int32sl,  # lod?
            "u07" / Int32sl,
            "u10" / GbxVec3,  # related to frame3?
            "u11" / Int32sl,
        ),
    ),
    "u04" / GbxBool,
    "spriteOriginYWasWronglyTop" / GbxBool,
    "mapping" / GbxLightMapCacheMapping,
    "gpuPlatform" / GbxELightMapCacheEPlugGpuPlatform,
    "allocatedTexelByMeter" / GbxFloat,
    "u08" / Int32sl,
    "u09" / Int32sl,
    "rest" / GreedyBytes,
)

# 09003 CPlugCrystal

GbxCrystal = Struct(
    "version" / Int32ul,  # 37
    "u06" / Int32sl,  # 4
    "u07" / Int32sl,  # 3
    "u08" / Int32sl,  # 4
    "u09" / GbxFloat,  # 64
    "u10" / Int32sl,  # 2
    "u11" / GbxFloat,  # 128
    "u12" / Int32sl,  # 1
    "u13" / GbxFloat,  # 192
    "u14" / Int32sl,  # 0 - SAnchorInfo array?
    "groups"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / Int32sl,
            "u02" / Byte,  # bool?
            "u03" / Int32sl,  # -1, nodref?
            "name" / GbxString,
            "u04" / Int32sl,  # -1, nodref?
            "u05" / PrefixedArray(Int32ul, Int32sl),
        ),
    ),
    "isEmbeddedCrystal" / GbxBoolByte,
    "u30" / Int32sl,  # 0
    "u31" / Int32sl,  # 0
    "embeddedCrystal"
    / Struct(
        "positions" / PrefixedArray(Int32ul, GbxVec3),
        "edgesCount" / Int32ul,
        "unfacedEdgesCount" / Int32ul,
        "unfacedEdges" / GbxOptimizedIntArray(this.unfacedEdgesCount * 2),
        "facesCount" / Int32ul,
        "uvs" / PrefixedArray(Int32ul, GbxVec2),
        "faceIndiciesCount" / Int32ul,
        "faceIndicies" / GbxOptimizedIntArray(this.faceIndiciesCount),
        "faces"
        / Array(
            this.facesCount,
            Struct(
                "vertCount" / Int8ul,
                "inds" / GbxOptimizedIntArray(this.vertCount + 3, lambda this: len(this._.positions)),
                "material_index" / GbxOptimizedInt(1),  # TODO
                "group_index" / GbxOptimizedInt(1),  # TODO
            ),
        ),
        "u22" / Int32sl,
    ),
)
GbxCrystal_Geometry = Struct(
    "crystal" / GbxCrystal,
    "u01" / PrefixedArray(Int32ul, Int32sl),
    "isVisible" / GbxBool,
    "isCollidable" / GbxBool,
)
GbxCrystal_Trigger = Struct("crystal" / GbxCrystal, "u01" / PrefixedArray(Int32ul, Int32sl))

body_chunks[0x09003003] = Struct(
    "version" / Int32ul,
    "materials" / PrefixedArray(Int32ul, GbxMaterial),
)
body_chunks[0x09003004] = Struct(
    "version" / Int32ul,
    "u01_size" / Int32ul,
    "u01" / Bytes(this.u01_size),
    "u02" / Bytes(4),
)
body_chunks[0x09003005] = Struct(
    "version" / Int32ul,
    "layer_count" / Rebuild(Int32ul, lambda this: len(this.layers)),
    "layers"
    / Array(
        this.layer_count,
        Struct(
            "type" / GbxELayerType,
            "version" / Int32ul,
            "u02" / GbxBool,
            "id" / GbxLookbackString,
            "name" / GbxString,
            "is_enabled" / If(this.version >= 1, GbxBool),
            "type_version" / Int32ul,
            "content"
            / Switch(
                this.type,
                {
                    GbxELayerType.Geometry: GbxCrystal_Geometry,
                    GbxELayerType.Trigger: GbxCrystal_Trigger,
                    GbxELayerType.Cubes: GreedyBytes,
                },
                GreedyBytes,
            ),
        ),
    ),
)
body_chunks[0x09003006] = Struct(
    "version" / Int32ul,
    "u01" / If(this.version == 0, PrefixedArray(Int32ul, GbxVec2)),
    StopIf(this.version < 1),
    "u02" / PrefixedArray(Int32ul, Int16sl[2]),
    StopIf(this.version < 2),
    "u03Count" / Int32ul,
    "u03" / GbxOptimizedIntArray(this.u03Count),
)
body_chunks[0x09003007] = Struct(
    "version" / Int32ul,
    "u01" / PrefixedArray(Int32ul, GbxFloat),
    "u02" / PrefixedArray(Int32ul, Int32sl),
)

# 09005 CPlugSolid

GbxPlugSolidUvGroup = Struct(
    "u01" / GbxFloat,
    "u02" / GbxFloat,
    "u03" / GbxFloat,
    "u04" / GbxFloat,
    "u05" / GbxFloat,
)
GbxPlugSolidPreLightGen = Struct(
    "version" / Int32ul,
    "u01" / Int32sl,
    "u02" / GbxFloat,
    "u03" / GbxBool,
    "u04" / GbxFloat,
    "u05" / GbxFloat,
    "u06" / GbxFloat,
    "u07" / GbxFloat,
    "u08" / GbxFloat,
    "u09" / GbxFloat,
    "u10" / GbxFloat,
    "u11" / GbxFloat,
    "u12" / Int32sl,
    "u13" / Int32sl,
    "u14" / PrefixedArray(Int32ul, GbxBox),
    StopIf(this.version < 1),
    "u15" / PrefixedArray(Int32ul, GbxPlugSolidUvGroup),
)
GbxPlugSolidLocatedInstance = Struct(
    "u01" / Int32sl,
    "u02" / GbxIso4,
)

body_chunks[0x09005000] = Struct("typeAndIndex" / Int32sl)
body_chunks[0x09005010] = Struct("u01" / GbxNodeRef)
body_chunks[0x09005011] = Struct(
    "u01" / GbxBool,
    "u02" / GbxBool,
    "u03" / If(this.u02, GbxBool),
    "tree" / GbxNodeRef,
)
body_chunks[0x09005017] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 3),  # 3
    "u09" / If(this.version >= 3, GbxBool),
    "solidPreLightGen" / If(this.u09, GbxPlugSolidPreLightGen),
    # TODO version < 3
    StopIf(this.version < 2),
    "fileWriteTime" / GbxFileTime,
)
body_chunks[0x09005019] = Struct(
    "version" / Int32ul,  # 5
    "_listVersion1" / Int32ul,
    "u01" / PrefixedArray(Int32ul, GbxNodeRef),  # CPlugSound
    "_listVersion2" / Int32ul,
    "u02" / PrefixedArray(Int32ul, GbxNodeRef),  # CPlugParticleEmitterModel
    "u03" / PrefixedArray(Int32ul, GbxPlugSolidLocatedInstance),
    "u04" / PrefixedArray(Int32ul, GbxPlugSolidLocatedInstance),
    StopIf(this.version < 1),
    "u05" / Int32sl,
    StopIf(this.version < 2),
    "u06" / PrefixedArray(Int32ul, GbxLookbackString),
    "u07" / PrefixedArray(Int32ul, GbxIso4),
    StopIf(this.version < 3),
    "u08" / GbxString,
    StopIf(this.version < 4),
    "u09" / Int32sl,
    StopIf(this.version < 5),
    "u10" / GbxNodeRef,  # CPlugPath
)
# body_chunks[0x0900501A] = Struct(
#     "version" / ExprValidator(Int32ul, obj_ == 4),  # 4
#     "u01"
#     / Struct(
#         "version" / Int32ul,  # version
#         "u01" / GbxNodeRef, # CPlugVisualIndexedTriangles
#         TODO
#     ),
# )

# 09006 CPlugVisual

body_chunks[0x09006001] = Struct("u01" / GbxNodeRef)
body_chunks[0x09006004] = Struct("u01" / GbxNodeRef)
body_chunks[0x09006005] = Struct("sub_visuals" / PrefixedArray(Int32ul, GbxInt3))
body_chunks[0x09006009] = Struct("has_vertex_normals " / GbxBool)
body_chunks[0x0900600B] = Struct(
    "splits " / PrefixedArray(Int32ul, Struct("u01" / Int32sl, "u02" / Int32sl, "u03" / GbxBox))
)


# def convert_chunk_flags_to_flags(chunk_flags, ctx):
#     flags = 0
#     flags |= chunk_flags & 15
#     flags |= (chunk_flags << 1) & 0x20
#     flags |= (chunk_flags << 2) & 0x80
#     flags |= (chunk_flags << 2) & 0x100
#     flags |= (chunk_flags << 13) & 0x100000
#     flags |= (chunk_flags << 13) & 0x200000
#     flags |= (chunk_flags << 13) & 0x400000

#     return flags


# def convert_flags_to_chunk_flags(flags, ctx):
#     # TODO
#     chunk_flags = flags & 15  # bit0-4
#     chunk_flags |= (flags >> 1) & 0x10  # bit 5
#     chunk_flags |= (flags >> 2) & 0x20  # bit 7
#     chunk_flags |= (flags >> 2) & 0x40  # bit 8
#     chunk_flags |= (flags >> 13) & 0x80  # bit 20
#     chunk_flags |= (flags >> 13) & 0x100  # bit 21
#     chunk_flags |= (flags >> 13) & 0x200  # bit 22

#     return chunk_flags


body_chunks[0x0900600D] = Struct(
    "ChunkFlags"  # only on bits 0x7001af
    / ByteSwapped(
        BitStruct(
            Padding(9),
            "bit22" / Flag,
            "bit21" / Flag,  # vert_u04 stored as Dec4N?
            "bit20" / Flag,
            Padding(11),
            "bit8" / Flag,
            "bit7" / Flag,
            Padding(1),
            "HasVertexNormals" / Flag,
            "isIndexationStaticBit" / Flag,
            "isGeometryStaticBit" / Flag,
            "SkinIndexCount" / BitsInteger(3),  # max 4
        )
    ),
    "TexCoordCount" / Int32ul,
    "VertexCount" / Int32ul,
    "vertexStreams" / PrefixedArray(Int32ul, GbxNodeRef),
    "texCoords"
    / Array(
        this.TexCoordCount,
        Struct(
            # TODO recheck
            "version" / Int32ul,
            "count" / IfThenElse(this.version >= 3, Int32ul, Computed(this._.count)),
            "flags" / If(this.version >= 3, Int32ul),
            "tex_coords"
            / Array(
                this.count,
                Struct(
                    "uv" / GbxVec2,
                    "u01" / If(lambda this: 1 <= this._.version < 3, Int32sl),
                    "u02" / If(lambda this: this._.version == 2, Int32sl),
                ),
            ),
            "u01"
            / If(
                lambda this: this.flags,
                Array(lambda this: this.count * (this.flags & 0xFF), GbxFloat),
            ),
        ),
    ),
    "visualSkin"
    / If(
        lambda this: this.ChunkFlags.SkinIndexCount > 0,
        Struct(
            "u01" / GbxBool,
            "u02" / Int32sl,
            "u03" / If(this._.version >= 3, GbxBool),
            "u04" / If(this._.version >= 3, GbxBool),
            "u05"
            / If(
                this.u03,
                Array(
                    lambda this: this._.VertexCount,
                    GbxFloat[this._.ChunkFlags.SkinIndexCount],
                ),  # or GbxVec3?
            ),
            "boneNames" / PrefixedArray(Int32ul, GbxLookbackString),
            StopIf(this._.version < 2),
            "boneIndices" / PrefixedArray(Int32ul, Int32sl),
        ),
    ),
    "u01" / GbxBox,
)
body_chunks[0x0900600E] = Struct(
    *body_chunks[0x0900600D].subcons,
    "bitmapElemToPacks" / PrefixedArray(Int32ul, Struct("u01" / Bytes(20))),
)
body_chunks[0x0900600F] = Struct(
    "version" / Int32ul,
    *body_chunks[0x0900600E].subcons,
    StopIf(this.version < 5),
    "u02" / PrefixedArray(Int32ul, Int16sl),
    StopIf(this.version < 6),
    "u03" / Int32ul,
    "ByteCount" / Int32ul,
    "u04" / If(this.ByteCount > 0, Bytes(this.ByteCount - 4)),
)
body_chunks[0x09006010] = Struct("version" / Int32ul, "morph_count" / ExprValidator(Int32ul, obj_ == 0))

# 0900C CPlugSurface

GbxSurfTypeToStruct = {}
GbxSurf = Struct(
    "type" / GbxESurfType,
    "data"
    / Switch(
        this.type,
        GbxSurfTypeToStruct,
        GbxBytesUntilFacade,
    ),
    "u01" / GbxVec3,
    # / If(this._.surfVersion >= 2, GbxVec3),  #  mainDir? like for boost its dir?
)
GbxSurfTypeToStruct[GbxESurfType.Sphere] = Struct(
    "u01" / GbxFloat,
    "u02" / Int16sl,
)
GbxSurfTypeToStruct[GbxESurfType.Mesh] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 7),
    "vertices" / PrefixedArray(Int32ul, GbxVec3),
    "triangles"
    / PrefixedArray(
        Int32ul,
        Struct(
            "face" / GbxInt3,
            "materialId" / GbxPlugSurfaceMaterialId,
            "materialIndex" / Int16sl,
        ),
    ),
)
GbxSurfTypeToStruct[GbxESurfType.Compound] = Struct(
    "surfVersion" / Computed(this._._.surfVersion),
    "surfaces" / PrefixedArray(Int32ul, GbxSurf),
    "locs" / Array(len_(this.surfaces), GbxIso4),
    "boneIndexes" / PrefixedArray(Int32ul, Int16ul),
)
GbxSurfConvexPolyhedron = Struct(
    "version" / Int32ul,
    "u01" / Int32sl,  # if != 0, other code
    "AABB" / GbxBox,  # 0x88
    "vertices" / PrefixedArray(Int32ul, GbxVec3),
    # "u01" / PrefixedArray(Int32ul, Int32sl),
    # "u02" / PrefixedArray(Int32ul, Int32sl[2]),
    "u05" / Int16sl,
)
body_chunks[0x0900C003] = Struct(
    "version" / Int32ul,  # 4
    "surfVersion" / If(this.version >= 2, Int32ul),
    "surf" / GbxSurf,
    "materials"
    / PrefixedArray(
        Int32ul,
        Struct(
            "hasMaterial" / GbxBool,  # Rebuild(GbxBool, lambda this: this.material is not None),
            "material" / If(this.hasMaterial, GbxNodeRef),
            "materialId" / If(lambda this: not this.hasMaterial, GbxPlugSurfaceMaterialId),
        ),
    ),
    "u01" / If(lambda this: len(this.materials) > 0, Int32sl),  # TODO check condition
    "materialsIds" / PrefixedArray(Int32ul, GbxPlugSurfaceMaterialId),
    "skel" / If(this.version >= 1, GbxNodeRef),
)

# 0901D CPlugLight

body_chunks[0x0901D003] = Struct(
    "version" / Int32ul,  # 1
    "image" / GbxNodeRef,  # CPlugFileImg
    "u01" / GbxFloat,
    "u02" / GbxFloat,
    StopIf(this.version < 1),
    "u03" / Int32sl,
)
body_chunks[0x0901D004] = Struct(
    "version" / Int32ul,  # 0
    "u01_CGxLightSpot" / GbxNodeRef,  # CGxLightSpot
    "u02" / Int32sl,
    # "u03_CPlugMaterialColorTargetTable" / GbxNodeRef,  # CPlugMaterialColorTargetTable
    "rest" / GbxBytesUntilFacade,
)

# 0902C CPlugVisual3D


def get_chunk_900600F(ctx):
    for chunk in ctx._._._array:
        if chunk.chunkId == 0x900600F:
            return chunk.chunk


body_chunks[0x0902C002] = Struct("u01" / GbxNodeRef)
body_chunks[0x0902C004] = Struct(
    "flags" / Computed(lambda ctx: get_chunk_900600F(ctx).ChunkFlags),
    "readNormals" / Computed(lambda this: not this.flags.bit22 or this.flags.HasVertexNormals),
    "u02" / Computed(lambda this: not this.flags.bit22 or this.flags.bit8),
    "u03" / Computed(lambda this: this.flags.bit20),  # or CPlugVisualSprite
    "vertices"
    / IfThenElse(
        # TODO verify
        this.u01 and not this.u03 and not this.flags.bit21 and this.u02,
        Bytes(0x28)[lambda ctx: get_chunk_900600F(ctx).VertexCount],
        If(
            lambda ctx: len(get_chunk_900600F(ctx).vertexStreams) == 0,
            Array(
                lambda ctx: get_chunk_900600F(ctx).VertexCount,
                Struct(
                    "position" / GbxVec3,
                    "normal"
                    / If(
                        lambda this: this._.readNormals,
                        IfThenElse(
                            this._.u03,
                            GbxDec3N,
                            GbxVec3,
                        ),
                    ),
                    "u01"
                    / IfThenElse(
                        this._.u02,
                        IfThenElse(
                            this._.flags.bit21,
                            GbxUDec4N,
                            GbxVec4,
                        ),
                        Computed(Container(x=1.0, y=1.0, z=1.0, w=1.0)),
                    ),
                ),
            ),
        ),
    ),
    "tangentsU" / PrefixedArray(Int32ul, IfThenElse(this._.flags.bit20, GbxDec3N, GbxVec3)),
    "tangentsV" / PrefixedArray(Int32ul, IfThenElse(this._.flags.bit20, GbxDec3N, GbxVec3)),
)

# 0903A CPlugMaterialCustom

body_chunks[0x0903A004] = Struct(
    "u01" / PrefixedArray(Int32ul, Int32sl),
)
body_chunks[0x0903A00A] = Struct(
    "u01"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / GbxLookbackString,
            "count1" / Int32sl,
            "count2" / Int32sl,
            "u02" / GbxBool,
            "u03" / GbxFloat[this.count1][this.count2],
        ),
    ),
    "u02"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / GbxLookbackString,
            "count1" / Int32sl,
            "count2" / Int32sl,
            "u02" / GbxBool,
            "u03" / GbxFloat[this.count1][this.count2],
        ),
    ),
)
body_chunks[0x0903A00C] = Struct(
    "u01"
    / PrefixedArray(
        Int32ul,
        Struct(
            "name" / GbxLookbackString,
            "u01" / GbxBool,
        ),
    ),
)
body_chunks[0x0903A012] = Struct(
    "u01" / Int32sl,
)
body_chunks[0x0903A013] = Struct(
    "version" / Int32ul,  # 0
    "textures"
    / PrefixedArray(
        Int32ul,
        Struct(
            "name" / GbxLookbackString,
            "u01" / Int32sl,
            "textureNod" / GbxNodeRef,
            "u03" / Int32sl,
            "u04" / Int32sl,
        ),
    ),
)
body_chunks[0x0903A014] = Struct(
    "version" / Int32ul,  # 1
    "u01" / PrefixedArray(Int32ul, Pass),  # TODO
)
body_chunks[0x0903A015] = Struct(
    "version" / Int32ul,  # 2
    "u01" / Int32sl,
    "u02" / GbxString,
    "u03" / GbxString,
    StopIf(this.version < 2),
    "u04" / GbxString,
    "u05" / GbxString,
)
body_chunks[0x0903A016] = Struct(
    "version" / Int32ul,  # 2
    "u01" / Bytes(8),
    "u02" / Bytes(8),
    StopIf(this.version < 1),
    "u03" / Int32sl,
    "u04"
    / If(
        lambda this: (this.u01[0] & 1) != 0,
        Struct(  # SPlugVisibleFilter
            "u01" / Hex(Int16ul),
            "u02" / Hex(Int16ul),
        ),
    ),
)

# 0904F

body_chunks[0x0904F006] = Struct(
    "listVersion" / Int32sl,
    "children" / PrefixedArray(Int32ul, GbxNodeRef),
)
body_chunks[0x0904F00D] = Struct(
    "name" / GbxLookbackString,
    "u02" / GbxLookbackString,
)
body_chunks[0x0904F011] = Struct("funcTree" / GbxNodeRef)
body_chunks[0x0904F016] = Struct(
    "visual" / GbxNodeRef,
    "shaderFile" / GbxNodeRef,
    "surface" / GbxNodeRef,
    "generator" / GbxNodeRef,
)
body_chunks[0x0904F01A] = Struct(
    "flags" / Int32ul,
    "translation" / If(lambda this: (this.flags & 4) != 0, GbxIso4),
)

# 09051 CPlugTreeGenerator

body_chunks[0x09051000] = Struct(
    "version" / Int32ul,
)

# 09056 CPlugVertexStream

body_chunks[0x09056000] = Struct(
    "version" / Int32ul,
    "num_vertices" / Int32sl,
    "u01" / Int32sl,
    "baseVertexStream" / GbxNodeRef,
    StopIf(lambda this: this.num_vertices == 0 or this.baseVertexStream != -1),
    "DataDecl"
    / PrefixedArray(
        Int32ul,
        Struct(
            "header"
            / ByteSwapped(
                BitStruct(
                    "u20" / BitsInteger(20),
                    "PtrOffset" / BitsInteger(10),
                    "u2" / BitsInteger(2),
                    "Space" / GbxEPlugVDclSpace,  # 4 bits
                    "Stride" / BitsInteger(10),
                    "Type" / GbxEPlugVDclType,  # 9 bits
                    "Name" / GbxEPlugVDcl,  # 9 bits
                )
            ),
            StopIf(this.header.PtrOffset == 0),
            "iDataDeclShared" / Int16ul,  # TODO check
            "Offset" / Int16ul,
        ),
    ),
    "compressFloat3InLocal3D" / GbxBool,  # always true for version > 0?
    "Data"
    / Array(
        lambda this: len(this.DataDecl),
        Switch(
            lambda this: "Dec3N"
            if this.DataDecl[this._index].header.Space == "Local3D"
            and this.DataDecl[this._index].header.Type == "Float3"
            and this.compressFloat3InLocal3D
            else this.DataDecl[this._index].header.Type,
            {
                "Float1": Float32l[this.num_vertices],
                "Float2": GbxVec2[this.num_vertices],
                "Float3": GbxVec3[this.num_vertices],
                "Float4": GbxVec4[this.num_vertices],
                "ColorD3D": GbxColor[this.num_vertices],
                "UByte4": Int8ul[4][this.num_vertices],
                "Short2": Int16sl[2][this.num_vertices],
                "Short4": Int16sl[4][this.num_vertices],
                "UByte4N": Bytes(4)[this.num_vertices],
                "Short2N": Bytes(4)[this.num_vertices],
                "Short4N": Bytes(8)[this.num_vertices],
                "UShort2N": Bytes(4)[this.num_vertices],
                "UShort4N": Bytes(8)[this.num_vertices],
                "UDec3": Bytes(4)[this.num_vertices],
                "Dec3N": GbxDec3N[this.num_vertices],
                "Half2": Int16sl[2][this.num_vertices],
                "Half4": Int16sl[4][this.num_vertices],
            },
        ),
    ),
)

# 09057 CPlugIndexBuffer

body_chunks[0x09057000] = Struct(
    "version" / Int32ul,
    "indices" / PrefixedArray(Int32ul, Int16ul),
)
body_chunks[0x09057001] = Struct(
    "flags" / Int32ul,  # TODO check if not 2 what that means
    "indices" / PrefixedArray(Int32ul, Int16sl),
)

# 0906A CPlugVisualIndexed

body_chunks[0x0906A001] = Struct(
    "has_index_buffer" / GbxBool,  # or array length ? or version ?
    "index_buffer" / If(this.has_index_buffer, GbxBodyChunks),
)

# 09079 CPlugMaterial
body_chunks[0x09079001] = Struct(
    "material_fx" / GbxNodeRef,  # CPlugMaterialFx
)
body_chunks[0x09079007] = Struct(
    "custom_material" / GbxNodeRef,  # CPlugMaterialCustom
)
body_chunks[0x09079010] = Struct(
    "u01" / GbxFloat,
)
body_chunks[0x09079011] = Struct(
    "u01" / PrefixedArray(Int32ul, GbxLookbackString),
)
body_chunks[0x09079012] = Struct(
    "version" / Int32sl,  # 2
    StopIf(this.version < 1),
    "u01" / GbxString,
    "u02" / GbxFileTime,
    "u03" / Bytes(4 * 8),
    StopIf(this.version < 2),
    "u04" / Bytes(4),
)
body_chunks[0x09079013] = Struct(
    "u01" / PrefixedArray(Int32ul, GbxString),
)
body_chunks[0x09079015] = Struct(
    "version" / Int32ul,  # 7
    "baseMaterial" / GbxNodeRef,  # CPlugMaterial
    "u01"
    / IfThenElse(
        this.baseMaterial == -1,
        Struct(
            "u01" / Bytes(40),
        ),
        Struct(
            StopIf(this._.version < 6),
            "colorTargetTable" / PrefixedArray(Int32ul, GbxNodeRef),  # CPlugMaterialColorTargetTable
            StopIf(this._.version < 7),
            "waterArray" / GbxNodeRef,  # CPlugMaterialWaterArray
        ),
    ),
)
body_chunks[0x09079016] = Struct(
    "version" / Int32ul,
    "flags" / Bytes(4),
)  # 0
body_chunks[0x09079017] = Struct(
    "version" / Int32ul,  # 1
    StopIf(this.version < 1),
    "flags" / Bytes(4),
    "u01" / GbxVec2,
    "u02" / GbxString,
)
body_chunks[0x09079019] = Struct(
    "version" / Int32ul,  # 0
    StopIf(this.version < 1),
    "u01" / Int32sl,
    "flags" / If(this.u01 != 0, Bytes(4)),
)

# NPlugCurve

# TODO tag as NPlugCurve
# TODO what are the variants?

NPlugCurve = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 2),  # 2
    "u01" / Int32sl,
    "u02" / Int32sl,
    "u03" / Array(this.u01 * 2, GbxFloat),
)

NPlugCurve_Simple = Struct(
    "version" / Int8ul,  # 0
    "u01" / Int32sl,
    "u02" / GbxFloat[4],
    "u03" / GbxFloat[12],
)

# 090B2 CPlugParticleEmitterSubModel

body_chunks[0x090B202D] = Struct(
    "version" / Int32ul,  # 4
    "u01" / Int32sl,
    "u02" / If(this.version > 2, Int32sl),
    "u03" / If(this.version > 2, Int32sl),
    "u04" / Int32sl,
    "u05" / Int32sl,
    "u06" / Int32sl,
    "u07" / Int32sl,
    "u08" / Int32sl,
    "u09" / If(this.version < 2, Int32sl),
    StopIf(this.version < 1),
    "u10" / GbxLookbackString,
    StopIf(this.version < 4),
    "u11" / Int32sl,
)
body_chunks[0x090B202E] = Struct(
    "version" / Int32ul,  # 0
    "SplashModel" / GbxNodeRef,  # CPlugParticleSplashModel
)
body_chunks[0x090B202F] = Struct(
    "version" / Int32ul,  # 3
    "u01" / GbxVec3,
    StopIf(this.version < 1),
    "u02" / GbxIso4,
    StopIf(this.version < 2),
    "u03_curve" / NPlugCurve,
)
body_chunks[0x090B2030] = Struct(
    "version" / Int32ul,  # 0
    "u01" / GbxVec3,
)
body_chunks[0x090B2031] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 6),  # 14
    "u01" / Int32sl[3],
    "u02" / GbxFloat,
    "material" / GbxNodeRef,  # CPlugMaterial
    "shader" / If(this.material == -1, GbxNodeRef),  # CPlugShader
    "u03" / GbxString,
    "model" / If(lambda _: True, GbxNodeRef),  # TODO cond
    "u04" / If(this.version > 6, GbxIso4),
    "u05" / GbxVec2,
    "u06" / Int32sl,
    "u07" / GbxFloat,
    "u08" / GbxFloat,
    StopIf(this.version < 3),
    "u09" / GbxFloat,
    StopIf(this.version < 4),
    "u10" / Int32sl,
    StopIf(this.version < 5),
    "u11" / Int32sl,
    StopIf(this.version < 9),
    "u12" / Int32sl,
    StopIf(this.version < 10),
    "u13" / Int32sl,
    StopIf(this.version < 11),
    "u14" / Int32sl,
    StopIf(this.version < 13),
    "u15_curve" / NPlugCurve,
    StopIf(this.version < 13),
    "u16_curve" / NPlugCurve,
    "u17_curve" / NPlugCurve,
)
body_chunks[0x090B2032] = Struct(
    "version" / Int32ul,  # 0
    "u01" / Int32sl[8],  # common with 0x90b2025
)
body_chunks[0x090B2033] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 5),  # 5
    "u01" / GbxFloat[5],
    "u02" / Int32sl,
    "u03_curve" / NPlugCurve,
    "u04" / Int32sl,
    "u05_curve" / NPlugCurve,
    "u06" / Int32sl[3],
    "u07_curve" / NPlugCurve_Simple,
    "u08" / Int32sl,
    "u09" / Int32sl,
    "u10" / Int32sl,
    "u11" / GbxFloat,
    "u12" / Int32sl,
    "u13" / Int32sl,
    "u14_curve" / NPlugCurve,
    "u15" / GbxFloat[2],
    StopIf(this.version < 4),
    "u16" / Int32sl,
    "u17_curve" / NPlugCurve,
)
body_chunks[0x090B2034] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 3),  # 3
    "u01_lightBall" / GbxNodeRef,  # CGxLightBall
    "u02_curve" / NPlugCurve,
    "u03_curve" / NPlugCurve_Simple,
    StopIf(this.version < 1),
    "u04" / Int32sl,
    StopIf(this.version < 2),
    "u05" / Int32sl,
)
body_chunks[0x090B2035] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 1),  # 1
)
body_chunks[0x090B2036] = Struct(
    "version" / Int32ul,  # 0
    "u01" / Int32sl,
    "u02" / Int32sl,
    "u03" / Int32sl,
)
body_chunks[0x090B2037] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 1),  # 1
    "u01" / Int32sl,
    "u02" / Int32sl,
    "u03" / Int32sl,
    "u04_curve" / NPlugCurve,
    "u05_curve" / NPlugCurve,
    "u06" / GbxFloat[2],
    "u07" / Int32sl[2],
    "u08" / GbxFloat[4],
    "u09" / Int32sl,
    "u10_curve" / NPlugCurve,
    "u11" / GbxFloat[3],
)
body_chunks[0x090B2038] = Struct(
    "version" / Int32ul,  # 0
    "u01" / GbxFloat,
    "u02" / GbxFloat,
)
body_chunks[0x090B2039] = Struct(
    "version" / Int32ul,  # 0
    "u01" / GbxFloat[10],
    "u02" / GbxFloat,
)
body_chunks[0x090B203A] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 1),  # 1
    "particleGpuSpawn" / GbxNodeRef,  # CPlugParticleGpuSpawn
    "particleGpuModel" / GbxNodeRef,  # CPlugParticleGpuModel
)
body_chunks[0x090B203B] = Struct(
    "version" / Int32ul,  # 1
    "u01" / GbxFloat[10],
    StopIf(this.version < 1),
    "u02" / GbxFloat,
)

# 090B3 CPlugParticleEmitterModel

body_chunks[0x090B3000] = Struct(
    "listVersion" / Int32ul,
    "ParticleEmitterSubModels" / PrefixedArray(Int32ul, GbxNodeRef),
    # "rest" / GreedyBytes,
)
body_chunks[0x090B3001] = Struct(
    "name" / GbxLookbackString,
)
body_chunks[0x090B3002] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 2),  # 4
    "u01" / Int32sl,
    StopIf(this.version < 3),
    "u02" / If(this.version == 3, Bytes(0x18)),
    "u03" / GbxFloat,
)
body_chunks[0x090B3003] = Struct(
    "version" / Int32ul,  # 0
    "u01" / ExprValidator(Int32ul, obj_ == 0),  # array of CFastStringInt
)
body_chunks[0x090B3004] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 6),  # 6
    "u01" / GbxFloat,
    "u02" / Int32sl,
    "u03" / GbxFloat,
    "u04" / Int32sl,
    "u05" / GbxFloat,
    "u06" / GbxFloat,
    "u07" / Int32sl,
    "u08" / Int32sl,
    "u09" / GbxFloat[3],
    "u10" / Int32sl,
)

# 090B5 CPlugParticleSplashModel

body_chunks[0x090B5000] = Struct(
    "version" / Int32ul,  # 5
    "u01" / Int32sl[5],
    "u09" / GbxFloat[3],
    "u02" / If(this.version > 0, Int32sl),
    "u03" / Int32sl[6],
    "u10" / GbxFloat,
    "u11" / Int32sl,
    "u12" / GbxFloat[2],
    "u13" / Int32sl[3],
    "u14" / GbxFloat,
    StopIf(this.version < 2),
    "u05" / Int32sl,
    "u06" / Int32sl,
    StopIf(this.version < 3),
    "u07_curve" / NPlugCurve,
    StopIf(this.version < 4),
    "u08" / Int32sl[3],
)

# 090C5 CPlugParticleGpuSpawn

body_chunks[0x090C5000] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 1),  # 1
    "spawn"
    / Struct(
        "version" / Int32ul,  # 4
        "u02" / Int32sl,
        "u03" / If(this.version > 1, Int32sl),
        "u04" / Int32sl,
        "u05" / GbxFloat,
        "u06" / If(this.version > 2, Int32sl),
        "u07" / If(this.version > 3, Int32sl),
        "u08" / If(this.version > 3, GbxFloat[3]),
        "u09" / Int32sl,
        "u10" / GbxFloat,
        "u11" / GbxFloat,
        "u12" / Int32sl,
        "u13" / Int32sl,
        "u14" / Int32ul,  # 0 - 4
        "u15"
        / Switch(
            this.u14,
            {
                0: Pass,
                5: Pass,
                1: Int32sl[4],
                2: Int32sl[8],
                3: GbxFloat[6],  # TransYawPitchRoll
                4: Int32sl[4],
            },
        ),
    ),
)

# 090C6 CPlugParticleGpuModel

body_chunks[0x090C6000] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 6),  # 6
    "u01" / GbxFloat[4],
    StopIf(this.version < 2),
    "u02" / Int32sl,
    "u03" / Int32sl,
    StopIf(this.version < 3),
    "u04" / GbxFloat,
    StopIf(this.version < 5),
    "u05" / Int32sl,
    StopIf(this.version < 6),
    "u06" / Int32sl,
)
body_chunks[0x090C6001] = Struct(
    "version" / Int32ul,  # 3
    "u01" / Int32sl,
    "u02" / GbxFloat,
    StopIf(this.version < 1),
    "u03" / Int32sl,
    "u04" / Int32sl,
    StopIf(this.version < 2),
    "u05" / Int32sl,
    StopIf(this.version < 3),
    "u06" / Int32sl,
)
body_chunks[0x090C6002] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 7),  # 22
    "u01" / GbxFloat,
    "isTextureFid" / GbxBool,
    "texture" / IfThenElse(this.isTextureFid, GbxString, GbxNodeRef),  # CPlugBitmap
    "u02" / GbxVec2,
    "u03" / GbxFloat,
    "u04" / GbxFloat,
    "u05" / Int32sl,
    "u06" / Int32sl,
    "u07" / GbxFloat,
    "u08" / Int32sl,
    "u09" / Int32sl,
    "u10" / GbxFloat[3],
    StopIf(this.version <= 1),
    "u11" / Int32sl,
    StopIf(this.version <= 4),
    "u12" / Int32sl,
    StopIf(this.version <= 5),
    "u13" / Int32sl,
    "u14" / Int32sl,
    StopIf(this.version <= 8),
    "texture2" / GbxNodeRef,  # CPlugBitmap
    "u15" / Int32sl[4],
    "u16" / GbxFloat,
    StopIf(this.version <= 9),
    "u17" / GbxFloat,
    "u18" / Int32sl,
    StopIf(this.version <= 10),
    "u19" / Int32sl,
    "u20" / Int32sl,
    StopIf(this.version <= 11),
    "texture3" / GbxNodeRef,  # CPlugBitmap
    StopIf(this.version <= 12),
    "u21" / Int32sl,
    StopIf(this.version <= 13),
    "u22" / Int32sl,
    "u23" / GbxFloat,
    StopIf(this.version <= 14),
    "u24" / Int32sl,
    StopIf(this.version <= 15),
    "IsFogEmitter" / GbxBool,
    "FogEmissionRate" / GbxFloat,
    StopIf(this.version <= 16),
    "u27" / GbxFloat[3],
    StopIf(this.version <= 17),
    "texture4" / GbxNodeRef,  # CPlugBitmap
    StopIf(this.version <= 18),
    "u28" / Int32sl,
    StopIf(this.version <= 19),
    "u29" / GbxFloat[4],
    StopIf(this.version < 22),
    "u30" / GbxFloat,
)
body_chunks[0x090C6003] = Struct(
    "version" / Int32ul,  # 2
    "u01" / GbxFloat,
    "u02" / GbxFloat,
    "u03" / GbxFloat,
)

# 090F9 CPlugLightUserModel

body_chunks[0x090F9000] = Struct(
    "version" / Int32ul,  # 1
    "u01" / GbxFloat,
    "u02" / GbxFloat,
    "u03" / GbxFloat,
    "u04" / GbxFloat,
    "u05" / GbxFloat,
    "u06" / GbxFloat,
    "u07" / GbxFloat,
    "u08" / GbxFloat,
    "u09" / GbxFloat,
    "u10" / GbxFloat,
    "u11" / GbxFloat,
    "u12" / GbxFloat,
    StopIf(this.version < 1),
    "u13" / GbxFloat,
)

# 0912F CPlugDynaModel

body_chunks[0x0912F000] = Struct(
    "version" / Int32ul,  # 4
    "LinearMass" / GbxFloat,
    "MaxDistPerStep" / GbxFloat,
    "CenterOfMass" / GbxVec3,
    "InertialMatrix" / GbxMat3x3,
    "AngularSpeedClamp" / GbxFloat,
    StopIf(this.version < 1),
    "Use_TM_Simulation" / GbxBool,
    StopIf(this.version < 2),
    "SleepingMethod" / Enum(Byte, No=0, LowLinearVel_AngularVel=1, LowLinearVel=2, Reserved0=3),
    StopIf(this.version < 3),
    "EnableSubStepping" / GbxBool,
    StopIf(this.version < 4),
    "WaterModel" / GbxNodeRef,
)

# 09144 CPlugDynaObjectModel

body_chunks[0x09144000] = Struct(
    "version" / Int32ul,
    "IsStatic" / GbxBool,  # si c'est un dyna mais qui reste tjs statique
    "DynamizeOnSpawn" / GbxBool,
    "Mesh" / GbxNodeRef,
    "DynaShape" / GbxNodeRef,  # Boite de collision apres destruction, ne supporte pas mesh quelconque
    "StaticShape" / GbxNodeRef,  # Boite de collision avant destruction
    "DestructibleModel"
    / Struct(
        "BreakSpeedKmh" / If(this._.version > 1, GbxFloat),
        "Mass" / If(this._.version > 2, GbxFloat),
        "LightAliveDurationSc_Min" / If(this._.version > 4, GbxFloat),
        "LightAliveDurationSc_Max" / If(this._.version > 4, GbxFloat),
    ),
    # If version > 3
    "u01" / Int32sl,
    "u02" / Int32sl,
    "u03" / Byte,
    "u04" / Byte,
    "u05" / Int32sl,
    "u06" / Int32sl,
    # If version > 5
    "u07" / Byte,
    "u08" / Int32sl,
    "u09" / Int32sl,
    "LocAnim" / If(this.version > 6, GbxNodeRef),
    "u10" / If(this.version > 7, Int32sl),
    "LocAnimIsPhysical"
    / If(this.version > 9, GbxBool),  # LocAnim purement visuel ou pas. evitons les calculs physiques si pas necessaire
    "WaterModel" / GbxNodeRef,
)


def breakpoint(obj, ctx):
    return obj


def newPropSubEntityModel(obj, ctx):
    print(">>> newPropSubEntityModel")
    return obj


# 09145 SPlugPrefab

body_chunks[0x09145000] = Struct(
    "version" / Int32ul,
    "updatedTime" / GbxFileTime,
    "url" / GbxString,
    "u01" / Int32sl,  # kind of timestamp?
    "EntsCount" / Rebuild(Int32ul, len_(this.Ents)),
    "u02" / Int32sl,
    "Ents"
    / Array(
        this.EntsCount,
        Select(
            Struct(
                "model" / GbxNodeRef,
                "rot" / GbxQuat,
                "pos" / GbxVec3,
                # TODO generic meta param
                "params"
                / If(
                    True or this.model > 0,  # todo check this in ghidra
                    Struct(
                        "chunkId" / Hex(Int32sl),
                        "chunk"
                        / Switch(
                            this.chunkId,
                            {
                                -1: Pass,
                                # NPlugDynaObjectModel_SInstanceParams
                                0x2F0B6000: Struct(
                                    "version" / Int32sl,  # 2
                                    "PeriodSc" / GbxFloat,
                                    "TextureId" / Int32sl,
                                    "IsKinematic" / GbxBool,
                                    StopIf(this.version < 1),
                                    "PeriodScMax" / GbxFloat,
                                    "Phase01" / GbxFloat,
                                    "Phase01Max" / GbxFloat,
                                    StopIf(this.version < 2),
                                    "CastStaticShadow"
                                    / GbxBool,  # "!! Attention reserve a de rares objets dont l\'animation conserve a peu pres la shadow (tube qui tourne sur lui meme /ex), cette shadow (vue au loin) ne sera pas animee !!"
                                ),
                                # NPlugDyna_SPrefabConstraintParams
                                0x2F0C8000: Struct(
                                    "version" / Int32ul,  # 0
                                    "Ent1" / Int32sl,
                                    "Ent2" / Int32sl,
                                    "Pos1" / GbxVec3,
                                    "Pos2" / GbxVec3,
                                ),
                                # NPlugItemPlacement_SPlacement
                                0x2F0A9000: Struct(
                                    "version" / Int32ul,
                                    "iLayout" / Int32sl,
                                    "Options"
                                    / PrefixedArray(
                                        Int32ul,
                                        Struct(  # NPlugItemPlacement_SPlacementOption 0x30166000
                                            "RequiredTags" / GbxDictString,
                                        ),
                                    ),
                                ),
                                # NPlugItemPlacement_SPlacementGroup
                                0x2F0D8000: Struct(
                                    "version" / Int32ul,
                                    "Placements"
                                    / PrefixedArray(
                                        Int32ul,
                                        Struct(
                                            "version" / Int32ul,
                                            "iLayout" / Int32sl,
                                            "Options"
                                            / PrefixedArray(
                                                Int32ul,
                                                Struct(  # NPlugItemPlacement_SPlacementOption 0x30166000
                                                    "RequiredTags" / GbxDictString,
                                                ),
                                            ),
                                        ),
                                    ),
                                    "u01" / PrefixedArray(Int32ul, Int16sl),
                                    "u02" / PrefixedArray(Int32ul, GbxLoc),
                                ),
                                # NPlugStaticObjectModel_SInstanceParams
                                0x2F0D9000: Struct(
                                    "version" / Int32ul,  # 0
                                    "Phase01" / GbxFloat,
                                ),
                            },
                        ),
                    ),
                ),
                "u01" / Prefixed(Int32ul, GreedyBytes),  # string?
            ),
            GreedyBytes,
        ),
    ),
)


def check(obj, ctx):
    if obj:
        pass
    print(obj)
    return obj


# 09159 CPlugStaticObjectModel

body_chunks[0x09159000] = Select(
    Struct(
        "version" / Int32ul,  # 3
        "Mesh" / GbxNodeRef,  # CPlugSolid2Model
        "isMeshCollidable" / GbxBoolByte,
        "Shape" / If(lambda this: not this.isMeshCollidable, GbxNodeRef),  # CPlugSurface
    )
)

# 0915C CPlugFxSystem

GbxEFxSystemNodeType = Enum(
    Int32sl,
    No=-1,
    Parallel=0,
    Condition=1,
    SubFxSystem=2,
    UpdateVar=3,
    ParticleEmitter=4,
    SoundEmitter=5,
)

PlugFxSystemNodes = {}

#  Meta::CPlugFxSystemNode 0x2F0C1000
body_chunks[0x2F0C1000] = Struct(
    "type" / GbxEFxSystemNodeType,
    "node" / Switch(this.type, PlugFxSystemNodes),
)
#  Meta::CPlugFxSystemNode_Parallel 0x2F0C2000
PlugFxSystemNodes["Parallel"] = body_chunks[0x2F0C2000] = Struct(
    "name" / GbxLookbackString,
    "Children" / PrefixedArray(Int32ul, body_chunks[0x2F0C1000]),
)
#  Meta::CPlugFxSystemNode_Condition 0x2F0C3000
PlugFxSystemNodes["Condition"] = body_chunks[0x2F0C3000] = Struct(
    "name" / GbxLookbackString,
    "ConditionExpr" / GbxString,
    "Child" / body_chunks[0x2F0C1000],
)
#  Meta::CPlugFxSystemNode_SubFxSystem 0x2F0C5000
PlugFxSystemNodes["SubFxSystem"] = body_chunks[0x2F0C5000] = Struct(
    "name" / GbxLookbackString,
    "FxSystem" / body_chunks[0x2F0C1000],
)
#  Meta::CPlugFxSystemNode_UpdateVar 0x2F0C6000
PlugFxSystemNodes["UpdateVar"] = body_chunks[0x2F0C6000] = Struct(
    "name" / GbxLookbackString,
    "VarName" / GbxLookbackString,
    "ResetToDefaultIfInactive" / GbxBool,
    "UpdateVarExpr" / GbxString,
)
#  Meta::CPlugFxSystemNode_ParticleEmitter 0x2F0C4000
PlugFxSystemNodes["ParticleEmitter"] = body_chunks[0x2F0C4000] = Struct(
    # if version < 5 osef
    "name" / GbxLookbackString,
    "Model" / GbxNodeRef,  # CPlugParticleEmitterModel
    "JointName" / GbxLookbackString,
    "LocalOffsetExpr" / GbxString,
    "WorldOffsetExpr" / GbxString,
    "LinearVelInWExpr" / GbxString,
    "SpawnFreqModifierExpr" / GbxString,
    "ScaleExpr" / GbxString,
    "LAmbientExpr" / GbxString,
    "UpExpr" / GbxString,
    "DOVExpr" / GbxString,
    "OpacityExpr" / GbxString,
    "WaterTopExpr" / GbxString,
    "DOVAndUpAreLocalSpace" / GbxBool,
    "LinearHue01" / GbxString,
    "HueLightness" / GbxString,
)
#  Meta::CPlugFxSystemNode_SoundEmitter 0x2F0C7000
PlugFxSystemNodes["SoundEmitter"] = body_chunks[0x2F0C7000] = Struct(
    "name" / GbxLookbackString,
    "Model" / GbxNodeRef,  # CPlugSoundSurface
    "JointName" / GbxString,
    "PlayOnce" / GbxBool,
    "VolumeExpr" / GbxString,
    "VolumeExpr" / GbxString,
    "FadeOffDuration" / Int32sl,  # In seconds. If PlayOnce, 0 = the sound is not cut.
    "PitchExpr" / GbxString,
    "AudioGroupHandleExpr" / GbxString,
    "AudioBalanceGroup" / Int32sl,
    "Surface"
    / If(
        this.Model >= 0,
        Struct(
            "SurfaceIdExpr" / GbxString,
            "SpeedKmhExpr" / GbxString,
            "SkidIntensityExpr" / GbxString,
            "SkidSpeedKmhExpr" / GbxString,
        ),
    ),
)

body_chunks[0x0915C000] = Struct(
    "version" / Int32ul,  # 1
    "SystemNodesVersion" / Int32sl,  # 8
    "rootNode" / body_chunks[0x2F0C1000],
    "ContextClassId" / Int32sl,  # GbxLookbackString?
    "ExtraContextClassId" / Int32sl,  # GbxLookbackString?
    "VarsCount" / Int32ul,
    "VarsVersion" / Int32ul,  # 55
    "Vars"
    / Array(
        this.VarsCount,
        # SPlugGraphVar TODO
        Struct(
            "u01" / GbxLookbackString,
            "u02" / Byte,
            # TODO
        ),
    ),
)

# 0915D CPlugGameSkinAndFolder

body_chunks[0x0915D000] = Struct(
    "Remapping" / GbxNodeRef,
    "RemapFolder" / GbxString,
)
body_chunks[0x0915D001] = Struct("name" / GbxLookbackString)


# 09178 NPlugTrigger_SWaypoint

body_chunks[0x09178000] = Struct(
    "version" / Int32ul,  # 1
    "Type" / GbxEWayPointType,
    "TriggerShape" / GbxNodeRef,
    "NoRespawn" / GbxBool,
)

# 09179 NPlugTrigger_SSpecial
body_chunks[0x09179000] = Struct(
    "version" / Int32ul,
    "surf" / GbxNodeRef,
)

# 0917A CPlugSpawnModel
body_chunks[0x0917A000] = Struct(
    "version" / Int32ul,
    "Loc" / GbxIso4,
    "TorqueX" / GbxFloat,
    "TorqueDuration" / Int32ul,
    "DefaultGravitySpawn" / GbxVec3,
    "u01" / Int32sl,
)

# 0917B CPlugEditorHelper
body_chunks[0x0917B000] = Struct(
    "version" / Int32ul,
    "helper" / GbxNodeRef,
)

# 09187 NPlugItemPlacement_SClass
body_chunks[0x09187000] = Struct(
    "version" / Int32ul,
    "size_group" / GbxLookbackString,
    "compatible_groups_ids" / PrefixedArray(Int32ul, GbxLookbackString),
    "always_up" / GbxBool,
    "align_to_interior" / GbxBool,
    "align_to_world_dir" / GbxBool,
    "world_dir" / GbxVec3,
    "patch_layouts"
    / PrefixedArray(
        Int32ul,
        Struct(
            "item_count" / Int32ul,
            "item_spacing" / GbxFloat,
            "fill_align" / GbxEFillAlign,
            "fill_dir" / GbxEFillDir,
            "normed_pos" / GbxFloat,
            "u04" / GbxFloat,  # DistFromNormedPos?
            "only_on_groups" / PrefixedArray(Int32ul, GbxLookbackString),
            "altitude" / GbxFloat,
            "u06" / GbxFloat,  # FillBorderOffset?
        ),
    ),
    "group_cur_patch_layouts" / PrefixedArray(Int32ul, Int32sl),
)

# 09189 CPlugMediaClipList

body_chunks[0x09189000] = Struct(
    "u01" / Int32ul,
    "MediaClipFids" / PrefixedArray(Int32ul, GbxNodeRef),
)

# 090BA CPlugSkel

body_chunks[0x090BA000] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 12),
    "name" / GbxLookbackString,
    "joints"
    / PrefixedArray(
        Int16sl,
        Struct(
            "name" / GbxLookbackString,
            "parentIndex" / Int16sl,
            "jointPos" / If(this._._.version < 15, GbxQuat),  # todo check
            "jointRot" / If(this._._.version < 15, GbxVec3),  # todo check
            StopIf(this._._.version < 1),
            "GlobalLoc" / GbxIso4,
        ),
    ),
    StopIf(this.version < 2),
    "hasU03" / GbxBool,
    "u03"
    / If(
        this.hasU03,
        Struct(
            "u01"
            / PrefixedArray(
                Int32ul,
                Struct(
                    "bone0" / Int16sl,
                    "bone1" / Int16sl,
                    "bone2" / Int16sl,
                ),
            ),
            "u02"
            / PrefixedArray(
                Int32ul,
                Struct(
                    "u01" / Int32sl,
                    "u02" / Int32sl,
                    "u03" / Int32sl,
                    "u04" / Int32sl,
                ),
            ),
            "u03" / PrefixedArray(Int32ul, Int32sl),
            "u05" / Int16sl,
            "u06" / Int16sl,
        ),
    ),
    StopIf(this.version < 6),
    "sockets"
    / PrefixedArray(
        Int32ul,
        Struct(
            "name" / GbxLookbackString,
            "linkedJoint" / Int16sl,
            "loc" / GbxIso4,
        ),
    ),
    StopIf(this.version < 9),
    "hasU04" / GbxBool,
    "u04"
    / If(
        this.hasU04,
        Struct(
            "u01" / PrefixedArray(Int32ul, GbxLookbackString),
            "u02_SPlugSkelGlobalTargetInfo" / PrefixedArray(Int32ul, Int32sl),
            "u03_SPlugSkelGlobalTargetInfo" / PrefixedArray(Int32ul, Int32sl),
            "u04" / PrefixedArray(Int32ul, GbxQuat),
        ),
    ),
    StopIf(this.version < 10),
    "u05_SPlugSkelGlobalTargetInfo" / If(this.version <= 15, PrefixedArray(Int32ul, Int32ul)),
    "jointsLods" / If(this.version > 15, PrefixedArray(Int32ul, Int8ul)),
    "rotationOrder" / If(this.version > 13, PrefixedArray(Int32ul, GbxERotationOrder)),
    "u11" / If(this.version == 14, Int32sl),
    "cElem_0" / If(this.version == 14, Int32sl),  # = 0 ?
    "u10_func_rotation_order" / If(this.version >= 19, PrefixedArray(Int32ul, Int8ul)),  # enum?
    StopIf(this.version < 17),
    "cLod" / Int8ul,
    "LodMaxDists" / PrefixedArray(Int32ul, GbxFloat),
)

# 090BB CPlugSolid2Model

body_chunks[0x090BB000] = Struct(
    "version" / Int32ul,
    "u01" / GbxLookbackString,
    "shaded_geoms"
    / PrefixedArray(
        Int32ul,
        Struct(
            "visual_index" / Int32sl,
            "material_index" / Int32sl,
            "u01" / Int32sl,  # unused, -1
            StopIf(this._._.version < 1),
            "lod" / Int32sl,
            StopIf(this._._.version < 32),
            "u02" / Int32sl,
        ),
    ),
    "list_version_01" / If(this.version >= 6, ExprValidator(Int32ul, obj_ == 10)),
    "visuals" / If(this.version >= 6, PrefixedArray(Int32ul, GbxNodeRef)),
    "materials_names" / PrefixedArray(Int32ul, GbxLookbackString),
    "material_count" / IfThenElse(this.version >= 29, Int32ul, Computed(lambda this: 0)),
    "list_version_02" / If(this.material_count == 0, ExprValidator(Int32ul, obj_ == 10)),
    "materials" / If(this.material_count == 0, PrefixedArray(Int32ul, GbxNodeRef)),
    "skel" / GbxNodeRef,
    StopIf(this.version < 1),
    "lodDistances" / PrefixedArray(Int32ul, Float32l),  # lod distance?
    StopIf(this.version < 2),
    "VisCstType" / GbxEPlugSolidVisCstType,
    StopIf(this.version < 3),
    "hasPreLightGen" / GbxBool,
    "PreLightGen"
    / If(
        this.hasPreLightGen,
        Struct(
            "version" / Int32ul,  # 1
            "u01" / Int32sl,
            "lightmapSize" / Float32l,  # lightmap size in meters
            "u03" / GbxBool,
            "u04" / Float32l[4],
            "u05_u10" / Int32sl[6],
            "u14" / PrefixedArray(Int32ul, GbxBox),
            "uv_groups" / PrefixedArray(Int32ul, Float32l[5]),  # TODO
        ),
    ),
    StopIf(this.version < 4),
    "updatedTime" / GbxFileTime,
    StopIf(this.version < 5),
    "ImportString" / GbxString,
    StopIf(this.version < 7),
    "materialFolderName" / GbxString,
    "u09" / If(this.version >= 19, GbxString),
    StopIf(this.version < 8),
    "lights"
    / PrefixedArray(
        Int32ul,
        Struct(
            "name" / GbxLookbackString,
            "u02" / GbxBool,
            "u03" / If(this.u02, GbxNodeRef),  # CPlugLight
            "u04" / If(lambda this: not this.u02, GbxString),
            "u05" / GbxIso4,
            "u06" / Bytes(12),  # 6*4bytes
            "u12" / If(this._._.version >= 26, Bytes(12)),  # 3*4bytes, [1] and [2] = 0 if version < 26
            "u15" / GbxBool,
            "u16" / If(this.u15, Bytes(12)),  # 3*4bytes
        ),
    ),
    "material_insts_lt_v16" / If(this.version < 16, PrefixedArray(Int32ul, GbxNodeRef)),
    StopIf(this.version < 10),
    "lightUserModels" / PrefixedArray(Int32ul, GbxNodeRef),
    "light_insts" / PrefixedArray(Int32ul, Struct("model_index" / Int32ul, "socket_index" / Int32ul)),
    StopIf(this.version < 11),
    "damage_zone" / Int32sl,
    StopIf(this.version < 12),
    "flags" / Int32ul,
    # if version < 28, flags are adjusted, TODO?
    # flags &= 0xfffffbff
    StopIf(this.version < 13),
    "u12" / Int32sl,
    StopIf(this.version < 14),
    "creation_cmd" / GbxString,
    StopIf(this.version < 15),
    "material_count_lt_v29" / If(this.version < 29, Int32ul),
    "u14" / If(this.version >= 30, Int32sl),  # material_count?
    "custom_materials"
    / Array(
        lambda this: this.material_count if this.version >= 29 else this.material_count_lt_v29,
        GbxMaterial,
    ),
    StopIf(this.version < 17),
    "u15_bonesBoxes" / If(this.version < 21, PrefixedArray(Int32ul, GbxBox)),
    StopIf(this.version < 20),
    "bonesNames" / PrefixedArray(Int32ul, GbxLookbackString),
    StopIf(this.version < 22),
    "u17" / PrefixedArray(Int32ul, Int32sl),
    StopIf(this.version < 23),
    "u18" / ExprValidator(PrefixedArray(Int32ul, Pass), lambda obj, ctx: len(obj) == 0),  # TODO
    "u19" / PrefixedArray(Int32ul, Int32sl),
    StopIf(this.version < 24),
    "u20" / Int32sl,
    StopIf(this.version < 25),
    "icon" / GbxNodeRef,  # CPlugFileImg
    "u22" / GbxVec2,
    StopIf(this.version < 27),
    "u24" / GbxLookbackString,
    StopIf(this.version < 31),
    "u25" / PrefixedArray(Int32ul, Bytes(8)),
    StopIf(this.version < 33),
    "cst_0" / If(this.version == 33, ExprValidator(Int32ul, obj_ == 0)),
    "u26" / PrefixedArray(Int32ul, Int32sl[5]),
)
# body_chunks[0x090BB002] = Struct(
#     "img" / Prefixed(Int32ul, GreedyBytes),
#     "u01" / Bytes(60),
# )


# 090EA CPlugVehiclePhyModel
body_chunks[0x090EA003] = Struct("tunings" / GbxNodeRef)

# 090EB CPlugVehicleGearBox
# body_chucks[0x090EB]

# 090EC CPlugVehicleTunings
# body_chucks[0x090EC]

# 090F4 CPlugGameSkin
body_chunks[0x090F4003] = Struct("u01" / GbxString, "u02" / GbxString)
body_chunks[0x090F4005] = Struct(
    "version" / Int8ul,
    "relativeSkinDirectory" / GbxString,
    "u02" / GbxString,
    "u03" / GbxString,
    "fids"
    / PrefixedArray(
        Int8ul,
        Struct(
            "classId" / GbxChunkId,
            "type" / GbxString,
            "filePath" / GbxString,
            "u01" / Int32sl,
        ),
    ),
    "u04" / Bytes(16),
    # StopIf(this.version < 5),
    # "u04" / GbxString,
    # StopIf(this.version < 6),
    # "u05" / Bytes(4),
    # StopIf(this.version < 7),
    # "u06" / Bytes(4),
)

# 090FD CPlugMaterialUserInst
body_chunks[0x090FD000] = Struct(
    "version" / Int32ul,  # 11
    "isUsingGameMaterial" / If(this.version >= 11, GbxBoolByte),
    "materialName" / GbxLookbackString,
    "model" / GbxLookbackString,
    "baseTexture" / GbxString,  # baseMaterial?
    "surfacePhysicId" / GbxEPlugSurfacePhysicsId,
    "surfaceGameplayId" / If(this.version >= 10, GbxEPlugSurfaceGameplayId),
    StopIf(this.version < 1),
    "link"
    / IfThenElse(
        lambda this: (9 <= this.version < 11) or this.isUsingGameMaterial,
        GbxString,  # LinkFull
        GbxLookbackString,  # Link
    ),
    StopIf(this.version < 2),
    "csts"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / GbxLookbackString,
            "u02" / GbxLookbackString,
            "u03" / Int32sl,
        ),
    ),
    "color" / PrefixedArray(Int32ul, Int32sl),  # GbxVec2?
    StopIf(this.version < 3),
    "uvAnim"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / GbxLookbackString,
            "u02" / GbxLookbackString,
            "u03" / Float32l,
            "u04" / Int64ul,
            "u05" / If(this._._.version >= 5, GbxLookbackString),
        ),
    ),
    StopIf(this.version < 4),
    "u07" / PrefixedArray(Int32ul, GbxLookbackString),
    StopIf(this.version < 6),
    "userTextures"
    / PrefixedArray(
        Int32ul,
        Struct(
            "u01" / Int32sl,  # enum
            "textureName" / GbxString,  # LinkFull?
        ),
    ),
    StopIf(this.version < 7),
    "hidingGroup" / GbxLookbackString,
)
body_chunks[0x090FD001] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 3),
    "u01" / GbxNodeRef,
    "tiling_u" / GbxETexAddress,
    "tiling_v" / GbxETexAddress,
    "texture_size" / Float32l,
    StopIf(this.version < 4),
    "u02" / Int32sl,
    StopIf(this.version < 5),
    "is_natural" / GbxBool,
)
body_chunks[0x090FD002] = Struct(
    "version" / Int32ul,
    "u01" / Int32sl,
)

# 09118 CPlugPolyLine3

body_chunks[0x09118000] = Struct(
    "version" / Int32ul,
    "rest" / GbxBytesUntilFacade,
)  # 8

# 09119 CPlugPath

body_chunks[0x09119000] = Struct(
    "version" / Int32ul,  # 3
    "u01" / PrefixedArray(Int32ul, GbxNodeRef),
    StopIf(this.version < 2),
    "u02" / Int32sl,
    "hasU03" / GbxBoolByte,
    StopIf(this.version < 2),
    "u04" / Int32sl,
)

# 09128 CPlugRoadChunk

body_chunks[0x09128000] = Struct(
    "version" / Int32ul,  # 12
    "u01" / Int32sl,
    "u02" / Int32sl,
    "CenterVerts" / PrefixedArray(Int32ul, GbxVec3),
    "RightVerts" / PrefixedArray(Int32ul, GbxVec3),
    "LeftVerts" / PrefixedArray(Int32ul, GbxVec3),
    StopIf(this.version < 2),
    "Params" / Int32sl,
    "LinkVerts" / PrefixedArray(Int32ul, GbxVec3),
    StopIf(this.version < 3),
    "u03" / Int32sl,
    StopIf(this.version < 5),
    "TrafficLight" / Byte,
    "u05" / Byte,
    StopIf(this.version < 6),
    "u06" / Int32sl,
    "u07" / Int32sl,
    StopIf(this.version < 7),
    "u08" / Byte,
    StopIf(this.version < 8),
    "u09" / GbxLookbackString,
    StopIf(this.version < 9),
    "u10" / PrefixedArray(Int32ul, PrefixedArray(Int32ul, GbxVec3)),
    StopIf(this.version < 10),
    "u11" / Byte,
    "u12" / GbxLookbackString,
    "rot_v11" / If(this.version == 11, GbxVec3),
    StopIf(this.version < 12),
    "rot" / GbxQuat,
)

# 2E001 CGameCtnCollector
body_chunks[0x2E001009] = Struct(
    "pagePath" / GbxString,
    "hasIconFed" / GbxBool,
    "iconFed" / If(this.hasIconFed, GbxNodeRef),
    "u01" / GbxLookbackString,
)
body_chunks[0x2E00100B] = Struct("author" / GbxMeta)
body_chunks[0x2E00100C] = Struct("name" / GbxString)
body_chunks[0x2E00100D] = Struct("description" / GbxString)
body_chunks[0x2E00100E] = Struct(
    "icon_use_auto_render" / GbxBool,
    "icon_quarter_rotation_y" / Int32sl,
)
body_chunks[0x2E001010] = Struct(
    "version" / Int32ul,
    "u01" / GbxNodeRef,
    "skinDirectory" / GbxString,
    "u02" / If(lambda this: this.version >= 2 and len(this.skinDirectory) == 0, GbxNodeRef),
)
body_chunks[0x2E001011] = Struct(
    "version" / Int32ul,
    "isInternal" / GbxBool,
    "isAdvanced" / GbxBool,
    "catalogPosition" / Int32sl,
    "prodState" / If(this.version >= 1, GbxEProdState),
)
body_chunks[0x2E001012] = Struct(
    "version" / Int32ul,  # 0
    "u01" / Int32sl,  # 0x8c
    "u02" / Int32sl,  # 0x12
    "u03" / Int32sl,  # 0x94
)

# 2E002 CGameItemModel
body_chunks[0x2E002008] = Struct("nadeoSkinFids" / PrefixedArray(Int32ul, GbxNodeRef))
body_chunks[0x2E002009] = Struct("version" / Int32ul, "cameras" / PrefixedArray(Int32ul, GbxNodeRef))
body_chunks[0x2E00200C] = Struct("raceInterfaceFid" / GbxNodeRef)
body_chunks[0x2E002012] = Struct(
    "groundPoint" / GbxVec3,
    "painterGroundMargin" / GbxFloat,
    "orbitalCenterHeightFromGround" / GbxFloat,
    "orbitalRadiusBase" / GbxFloat,
    "orbitalPreviewAngle" / GbxFloat,
)
body_chunks[0x2E002015] = Struct("itemType" / GbxEItemType)
body_chunks[0x2E002019] = Struct(
    "version" / Int32ul,
    # "phy_model_custom" # TODO
    # "vis_model_custom" # TODO
    StopIf(this.version < 3),
    "defaultWeaponName" / GbxLookbackString,
    StopIf(this.version < 4),
    "PhyModelCustom" / GbxNodeRef,
    StopIf(this.version < 5),
    "VisModelCustom" / GbxNodeRef,
    StopIf(this.version < 6),
    "u01" / Int32ul,  # actions?
    StopIf(this.version < 7),
    "defaultCam" / GbxEDefaultCam,
    StopIf(this.version < 8),
    "EntityModelEdition" / GbxNodeRef,
    "EntityModel" / GbxNodeRef,
    StopIf(this.version < 13),
    "vfxFile" / GbxNodeRef,
    StopIf(this.version < 15),
    "MaterialModifier"
    / If(lambda this: this.EntityModel >= 0 or (this.EntityModel == -1 and this.EntityModelEdition == -1), GbxNodeRef),
)
body_chunks[0x2E00201A] = Struct("u01" / GbxNodeRef)
body_chunks[0x2E00201C] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 5),
    "defaultPlacement" / GbxNodeRef,
    # "u01" / Int32sl[5], ???
)
body_chunks[0x2E00201E] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 3),
    "archetypeRef" / GbxString,
    "u01" / If(lambda this: len(this.archetypeRef) == 0, Int32sl),
    StopIf(this.version < 5),
    "u02" / GbxString,
    StopIf(this.version < 6),
    "baseItem" / GbxNodeRef,
)
body_chunks[0x2E00201F] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 10),  # 12
    "waypointType" / GbxEWayPointType,
    "disableLightmap" / GbxBool,
    "u01" / Int32sl,
    StopIf(this.version < 11),
    "u08" / GbxBoolByte,  # if True, put EntityModel.StaticObject.u14 to 0 if -1
    StopIf(this.version < 12),
    "PodiumClipList" / GbxNodeRef,  # Podium only?
    "IntroClipList" / GbxNodeRef,
)
body_chunks[0x2E002020] = Struct(
    "version" / ExprValidator(Int32ul, obj_ >= 3),
    "iconFid" / GbxString,
    "u01" / Byte,
)

# 2E009 CGameWaypointSpecialProperty
body_chunks[0x2E009000] = Struct(
    "version" / Int32ul,  # 2
    "tag" / GbxString,
    "order" / Int32sl,
)

# 2E01C CGameVehicleModel
# these are indexes
body_chunks[0x2E01C000] = Struct(
    "skin_ix" / GbxNodeRef,
    "phyModel_ix" / GbxNodeRef,
    "visModel_ix" / GbxNodeRef,
    "u01" / Int32ul, # 0
    "u02" / Int32ul, # 0
    "u03" / Int32ul, # 0xFFFFFFFF
)

# 2E020 CGameItemPlacementParam

body_chunks[0x2E020000] = Struct(
    "version" / Int32ul,
    "flags" / Int16ul,
    "cubeCenter" / GbxVec3,
    "cubeSize" / Float32l,
    "gridSnap_HStep" / Float32l,
    "gridSnap_VStep" / Float32l,
    "gridSnap_HOffset" / Float32l,
    "gridSnap_VOffset" / Float32l,
    "flyStep" / Float32l,
    "flyOffset" / Float32l,
    "pivotSnapDistance" / Float32l,
)
body_chunks[0x2E020001] = Struct(
    "pivotPositions" / PrefixedArray(Int32ul, GbxVec3),
    "pivotRotations" / PrefixedArray(Int32ul, GbxQuat),
)
body_chunks[0x2E020003] = Struct(
    "version" / ExprValidator(Int32ul, obj_ == 3),  # 3
    # rest is a struct only in v3
    "subversion" / ExprValidator(Int32ul, obj_ == 10),
    "u02" / GbxLookbackString,
    "u03" / PrefixedArray(Int32ul, GbxLookbackString),
    "u04" / Int32sl,
    "u05" / Int32sl,
    "u06" / GbxFloat[4],
    "patchLayouts" / PrefixedArray(Int32ul, Pass),  # TODO
    "u07" / PrefixedArray(Int32ul, Int32sl),
)

body_chunks[0x2E020004] = Struct(
    "version" / Int32ul,  # 0
    "magnetLocs" / PrefixedArray(Int32ul, GbxPose3D),
)
body_chunks[0x2E020005] = Struct("item_placement" / GbxNodeRef)

# 2E025 CGameBlockItem

body_chunks[0x2E025000] = Struct(
    "version" / Int32ul,  # 1
    "ArchetypeBlockInfoId" / GbxLookbackString,
    "ArchetypeBlockInfoCollectionId" / GbxLookbackString,
    "CustomizedVariants" / GbxDict(Hex(Int32ul), GbxNodeRef),
    StopIf(this.version < 1),
    "hasCustomProps" / GbxBoolByte,
    "customProps"
    / If(
        this.hasCustomProps,
        Array(
            len_(this.CustomizedVariants),
            Struct(
                "flags"
                / ByteSwapped(  # little endian 32 bit
                    BitStruct(
                        Padding(4),
                        "hasU02" / Flag,
                        "hasU01" / Flag,
                        "hasSurf" / Flag,
                        "hasMesh" / Flag,
                    )
                ),
                "mesh" / If(this.flags.hasMesh, GbxNodeRef),  # CPlugStaticObjectModel
                "surf" / If(this.flags.hasSurf, GbxNodeRef),  # CPlugSurface
                "u01" / If(this.flags.hasU01, GbxBox),
                "u02" / If(this.flags.hasU02, GbxVec3),
            ),
        ),
    ),
)
body_chunks[0x2E025003] = Struct(
    "version" / Int32ul,  # 0
    "u01" / Array(lambda this: len(this._._._array[0].chunk.CustomizedVariants), GbxBoolByte),
)


# 2E026 CGameCommonItemEntityModelEdition

body_chunks[0x2E026000] = Struct(
    "version" / Int32ul,  # 8
    "itemType" / ExprValidator(GbxEItemType, obj_ == "Ornament"),
    "meshCrystal" / GbxNodeRef,
    "u01" / GbxString,
    "u02" / GbxNodeRef,  # if U01 is empty probably
    "u03" / ExprValidator(Int32ul, obj_ == 0),  # CPlugFileImg array
    "u04" / ExprValidator(Int32ul, obj_ == 0),  # SSpriteParam array
    "u05" / GbxNodeRef,
    "u06" / GbxNodeRef,
    "u07" / ExprValidator(Int32ul, obj_ == 0),  # SPlugLightBallStateSimple array
    "u08_u14" / GbxString[7],
    "u15" / GbxIso4,
    "u16" / GbxBool,
    "u21" / If(lambda this: not this.u16, GbxNodeRef),
    "u17" / GbxBool,
    "u18" / If(lambda this: this.u17, Int32sl),
    "u19" / If(lambda this: this.u17, GbxIso4),
    "u20" / Int32sl,
    StopIf(this.version < 1),
    "inventoryName" / GbxString,
    "inventoryDescription" / GbxString,
    "inventoryItemClass" / Int32sl,
    "inventoryOccupation" / Int32sl,
    StopIf(this.version < 6),
    "u22" / If(this.version < 8, GbxNodeRef),
)

# 2E027 CGameCommonItemEntityModel
body_chunks[0x2E027000] = Struct(
    "version" / Int32ul,  # 6
    "staticObject" / GbxNodeRef,
    StopIf(this.version < 2),
    "props"
    / Struct(
        "triggerShape" / GbxNodeRef,  # CPlugSurface
        "spawnLoc" / GbxIso4,
        "emitter" / GbxNodeRef,  # CPlugParticleEmitterModel
        "actions" / PrefixedArray(Int32ul, GbxNodeRef),  # CGameCtnPlaygroundActionModel
        "u03" / If(this._.version < 6, GbxNodeRef),
        "u04" / Array(5, GbxString),
        "u05" / GbxIso4,
        "u06" / ExprValidator(Int32sl, obj_ == 0),  # Array
    ),
    StopIf(this.version < 5),
    "u07" / GbxBoolByte,
)

# NPlugDyna_SConstraintModel 2F074000
body_chunks[0x2F074000] = Struct(
    "version" / Int32sl,
    "Type" / Int32sl,
    "Spring_Length" / GbxFloat,
    "Spring_DampingRatio" / GbxFloat,
    "Spring_FreqHz" / GbxFloat,
)

# 2F086 VegetTreeModel
body_chunks[0x2F086000] = Struct(
    "u01" / Bytes(4 * 4),  # version + lod 4 2 1?, number of things?
    "u02"  # parts?
    / PrefixedArray(
        Int32ul,
        Struct(
            "texture_d" / GbxNodeRef,
            "texture_n" / GbxNodeRef,
            "texture_r" / GbxNodeRef,
            "image_d" / GbxNodeRef,
            "image_n" / GbxNodeRef,
            "image_r" / GbxNodeRef,
            "u01" / GbxNodeRef[3],
            "u02" / GbxBoolByte,
        ),
    ),
    "u03" / PrefixedArray(Int32ul, GbxLookbackString),
    "u04" / Bytes(6),
    # "mesh1" / GbxNodeRef,
    # "u05" / Bytes(3),
    # "mesh2" / GbxNodeRef,
    # "u06" / Bytes(3),
    # "mesh3" / GbxNodeRef,
    # "u07" / Bytes(7),
    # "mesh4" / GbxNodeRef,
    # "u08" / Bytes(3),
    # "mesh5" / GbxNodeRef,
    # "u09" / Bytes(3),
    # "mesh6" / GbxNodeRef,
    "rest" / GreedyBytes,
)

# 2F0BC NPlugItem_SVariantList
body_chunks[0x2F0BC000] = Struct(
    "version" / Int32ul,  # 0
    "variants"
    / PrefixedArray(
        Int32ul,
        Struct(
            "Tags" / GbxDictString,
            "EntityModel" / GbxNodeRef,
            # "HiddenInManualCycle" / GbxBool, where is that from?
        ),
    ),
)

# 2F0CA KinematicConstraint
GbxSubAnimFunc = Struct(
    "ease" / GbxEAnimEase,
    "reverse" / GbxBoolByte,
    "duration" / Int32ul,
)
GbxAnimFunc = Struct(
    "TimeIsDuration" / GbxBool,
    "SubFuncs" / PrefixedArray(Int32ul, GbxSubAnimFunc),
)
body_chunks[0x2F0CA000] = Struct(
    "version" / Int32sl,
    "subVersion" / Int32sl,
    "TransAnimFunc" / GbxAnimFunc,
    "RotAnimFunc" / GbxAnimFunc,
    "ShaderTcType" / GbxEShaderTcType,
    "ShaderTcVersion" / Int32sl,
    "ShaderTcAnimFunc"
    / PrefixedArray(
        Int32ul,
        Struct(
            "Duration" / Int32ul,
            "TextureId" / Int32sl,
        ),
    ),
    "ShaderTcData_TransSub"
    / If(
        this.ShaderTcType == 1,
        Struct(
            "NbSubTexture" / Int32ul,
            "NbSubTexturePerLine" / Int32ul,
            "NbSubTexturePerColumn" / Int32ul,
            "TopToBottom" / GbxBool,
        ),
    ),
    "TransAxis" / GbxEAxis,
    "TransMin" / GbxFloat,
    "TransMax" / GbxFloat,
    "RotAxis" / GbxEAxis,
    "AngleMinDeg" / GbxFloat,
    "AngleMaxDeg" / GbxFloat,
)

# Headers chunks

header_chunks = {}

header_chunks[0x2E002000] = Struct("itemType" / GbxEItemType)

header_chunks[0x2E001003] = Struct(
    "meta" / GbxMeta,
    "version" / ExprValidator(Int32sl, obj_ >= 7),
    "pageName" / GbxString,
    StopIf(this.version < 3),
    "u01" / GbxLookbackString,
    "flags" / Hex(Int32sl),
    "catalogPosition" / Int16sl,
    "fileName" / GbxString,
    StopIf(this.version < 8),
    "prodState" / Enum(Byte, Aborted=0, GameBox=1, DevBuild=2, Release=3),
)

header_chunks[0x2E001004] = Struct(
    "width_and_webp" / Rebuild(Int16ul, lambda this: this.width + (0x8000 if this.webp else 0x0000)),
    "width" / Computed(this.width_and_webp & 0x7FFF),
    "height_and_webp" / Rebuild(Int16ul, lambda this: this.height + (0x8000 if this.webp else 0x0000)),
    "height" / Computed(this.height_and_webp & 0x7FFF),
    "webp" / Computed(lambda this: (this.width_and_webp & 0x8000) == (this.height_and_webp & 0x8000) == 0x8000),
    "data"
    / IfThenElse(
        this.webp,
        Struct("version" / Int16ul, "image" / Prefixed(Int32ul, GreedyBytes)),
        Array(
            lambda this: this.width * this.height,
            GbxColor,
        ),
    ),
)

header_chunks[0x090F4005] = body_chunks[0x090F4005]
header_chunks[0x03043003] = Struct(
    "version" / Int8ul,  # 11
    "mapInfo" / GbxMeta,
    "mapName" / GbxString,
    "kindInHeader" / GbxEMapKindInHeader,
    StopIf(this.version < 1),
    "u03" / Int32ul,
    "password" / GbxString,
    StopIf(this.version < 2),
    "decoration" / GbxMeta,
    StopIf(this.version < 3),
    "mapCoordOrigin" / GbxVec2,
    StopIf(this.version < 4),
    "mapCoordTarget" / GbxVec2,
    StopIf(this.version < 5),
    "u01" / Bytes(16),
    StopIf(this.version < 6),
    "mapType" / GbxString,
    "mapStyle" / GbxString,
    StopIf(this.version < 7),
    "u02" / If(this.version == 7, Int32sl),
    StopIf(this.version < 8),
    "lightmapCacheUID" / Int64ul,
    StopIf(this.version < 9),
    "lightmapVersion" / Int8ul,
    StopIf(this.version < 11),
    "titleID" / GbxLookbackString,
)
header_chunks[0x03043005] = Struct("xml" / GbxString)


def set_nodes_array(obj, ctx):
    ctx._root._params.nodes += [None] * obj
    return obj


def get_nodes_array(obj, ctx):
    return len(ctx._root._params.nodes)


def load_external_nodes(obj, ctx):
    ctx._root._params.nodes[obj.nodeIndex] = obj.ref

    return obj


def reset_lookbackstring(obj, ctx):
    ctx._root._params.gbx_data.pop("lookbackstring", None)
    return obj


def create_gbx_struct(gbx_body):
    return Struct(
        Const(b"GBX"),
        "version" / ExprValidator(Int16ul, obj_ == 6),
        Const(b"BU"),
        "bodyCompression" / Enum(Byte, compressed=ord("C"), uncompressed=ord("U")),
        "u01_R_or_E" / Bytes(1),
        "classId" / GbxChunkId,
        "header"
        / Select(
            Struct("size" / ExprValidator(Int32ul, obj_ == 0)),
            Struct(
                "corrupted_size" / ExprAdapter(Int32ul, lambda obj, ctx: obj, lambda obj, ctx: 0),
                "nb_nodes"
                / ExprValidator(
                    Peek(Int32ul[2]),
                    lambda obj, ctx: obj[0] < 1000 and obj[1] < 1000,
                ),
            ),  # fix corrupted chunk size
            Prefixed(
                Int32ul,
                Struct(
                    "entries"
                    / PrefixedArray(
                        Int32ul,
                        Struct(
                            "id" / GbxChunkId,
                            "meta"
                            / ByteSwapped(
                                BitStruct(
                                    "heavy" / Flag,
                                    "size"
                                    / Rebuild(
                                        BitsInteger(31),
                                        lambda this: len(
                                            header_chunks[this._.id].build(
                                                this._._._.data[this._index],
                                                gbx_data={
                                                    "lookbackstring_table": {},
                                                    "lookbackstring_index": 0,
                                                    "lookbackstring_version": False,
                                                },
                                            )
                                        )
                                        if this._.id in header_chunks
                                        else this.size,
                                    ),
                                )
                            ),
                        ),
                    ),
                    "data"
                    / Array(
                        lambda this: len(this.entries),
                        GbxLookbackStringContext(
                            Select(
                                Switch(
                                    lambda this: this.entries[this._index].id,
                                    header_chunks,
                                    default=Bytes(lambda this: this.entries[this._index].meta.size),
                                ),
                                Struct(
                                    "parse_header_chunk_failed"
                                    / Bytes(lambda this: this._.entries[this._index].meta.size)
                                ),
                            )
                        ),
                    ),
                ),
            ),
        ),
        "numNodes" / ExprAdapter(Int32ul, set_nodes_array, get_nodes_array),
        "referenceTable"
        / Struct(
            "numExternalNodes" / Int32ul,
            "externalFolders"
            / If(
                this.numExternalNodes > 0,
                Struct(
                    "ancestorLevel" / Int32ul,
                    "folders" / PrefixedArray(Int32ul, GbxFolders),
                ),
            ),
            "externalNodes"
            / Array(
                this.numExternalNodes,
                ExprAdapter(
                    Struct(
                        "flags"
                        / BitStruct(
                            "u01" / Hex(BytesInteger(29)),
                            "isRefResourceIndex" / Flag,
                            "u02" / Hex(BytesInteger(2)),
                        ),
                        "ref"
                        / IfThenElse(
                            this.flags.isRefResourceIndex,
                            "resourceIndex" / Int32ul,
                            "filename" / GbxString,
                        ),
                        "nodeIndex" / Int32ul,
                        "useFile" / GbxBool,
                        "folderIndex" / If(lambda this: not this.flags.isRefResourceIndex, Int32ul),
                    ),
                    load_external_nodes,
                    lambda obj, _: obj,
                ),
            ),
        ),
        "body"
        / GbxLookbackStringContext(
            IfThenElse(
                this.bodyCompression == "compressed",
                CompressedLZ0(gbx_body),
                gbx_body,
            )
        ),
        "rest" / Optional(GreedyBytes),
    )


GbxStruct = create_gbx_struct(GbxBody)
GbxStructWithoutBodyParsed = create_gbx_struct(GreedyBytes)
