const std = @import("std");
const builtin = @import("builtin");
const c = @import("c");

const icu_ver: u32 = if (builtin.os.tag.isDarwin()) 0 else @intCast(c.U_ICU_VERSION_MAJOR_NUM);

// Bug #22: single source of truth for ubrk_clone availability. Darwin's
// libicucore exports the unversioned symbol regardless of header version;
// elsewhere require a modern-enough ICU build macro.
pub const has_ubrk_clone = builtin.os.tag.isDarwin() or icu_ver >= 69;

const UbrkOpenFn = *const fn (c.UBreakIteratorType, [*c]const u8, [*c]const c.UChar, i32, [*c]c.UErrorCode) callconv(.c) ?*c.UBreakIterator;
const UbrkCloseFn = *const fn (?*c.UBreakIterator) callconv(.c) void;
const UbrkSetTextFn = *const fn (?*c.UBreakIterator, [*c]const c.UChar, i32, [*c]c.UErrorCode) callconv(.c) void;
const UbrkFirstFn = *const fn (?*c.UBreakIterator) callconv(.c) i32;
const UbrkNextFn = *const fn (?*c.UBreakIterator) callconv(.c) i32;
const UbrkGetRuleStatusFn = *const fn (?*c.UBreakIterator) callconv(.c) i32;
// Bug #22: resolved through our own canonical function type rather than
// @TypeOf(c.ubrk_clone), and it degrades to `null` instead of @compileError
// when the linked ICU predates ubrk_clone — the runtime fallback branch in
// tokenizeText exists precisely for those builds, so they must still compile.
// Callers gate on `has_ubrk_clone`.
const UbrkCloneFn = *const fn (?*const c.UBreakIterator, ?*c.UErrorCode) callconv(.c) ?*c.UBreakIterator;

const UStrToUTF8WithSubFn = *const fn ([*c]u8, i32, [*c]i32, [*c]const c.UChar, i32, c.UChar32, [*c]i32, [*c]c.UErrorCode) callconv(.c) [*c]u8;
const UStrToUTF8Fn = *const fn ([*c]u8, i32, [*c]i32, [*c]const c.UChar, i32, [*c]c.UErrorCode) callconv(.c) [*c]u8;

const UtransOpenUFn = *const fn ([*c]const c.UChar, i32, c.UTransDirection, [*c]const c.UChar, i32, [*c]c.UParseError, [*c]c.UErrorCode) callconv(.c) [*c]c.UTransliterator;
const UtransCloseFn = *const fn ([*c]c.UTransliterator) callconv(.c) void;
const UtransCloneFn = *const fn ([*c]const c.UTransliterator, [*c]c.UErrorCode) callconv(.c) [*c]c.UTransliterator;
const UtransTransUCharsFn = *const fn ([*c]const c.UTransliterator, [*c]c.UChar, [*c]i32, i32, i32, [*c]i32, [*c]c.UErrorCode) callconv(.c) void;

const UlocGetLanguageFn = *const fn ([*c]const u8, [*c]u8, i32, [*c]c.UErrorCode) callconv(.c) i32;
const UlocGetAvailableFn = *const fn (i32) callconv(.c) [*c]const u8;
const UlocCountAvailableFn = *const fn () callconv(.c) i32;

pub const ubrk_open: UbrkOpenFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("ubrk_open_{d}", .{icu_ver})
    else
        "ubrk_open";
    break :blk @extern(UbrkOpenFn, .{ .name = name });
};

pub const ubrk_close: UbrkCloseFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("ubrk_close_{d}", .{icu_ver})
    else
        "ubrk_close";
    break :blk @extern(UbrkCloseFn, .{ .name = name });
};

pub const ubrk_setText: UbrkSetTextFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("ubrk_setText_{d}", .{icu_ver})
    else
        "ubrk_setText";
    break :blk @extern(UbrkSetTextFn, .{ .name = name });
};

pub const ubrk_first: UbrkFirstFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("ubrk_first_{d}", .{icu_ver})
    else
        "ubrk_first";
    break :blk @extern(UbrkFirstFn, .{ .name = name });
};

pub const ubrk_next: UbrkNextFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("ubrk_next_{d}", .{icu_ver})
    else
        "ubrk_next";
    break :blk @extern(UbrkNextFn, .{ .name = name });
};

pub const ubrk_getRuleStatus: UbrkGetRuleStatusFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("ubrk_getRuleStatus_{d}", .{icu_ver})
    else
        "ubrk_getRuleStatus";
    break :blk @extern(UbrkGetRuleStatusFn, .{ .name = name });
};

pub const ubrk_clone: ?UbrkCloneFn = if (has_ubrk_clone) blk: {
    const name = if (builtin.os.tag.isDarwin())
        "ubrk_clone"
    else
        std.fmt.comptimePrint("ubrk_clone_{d}", .{icu_ver});
    break :blk @extern(UbrkCloneFn, .{ .name = name });
} else null;

pub const u_strToUTF8WithSub: UStrToUTF8WithSubFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("u_strToUTF8WithSub_{d}", .{icu_ver})
    else
        "u_strToUTF8WithSub";
    break :blk @extern(UStrToUTF8WithSubFn, .{ .name = name });
};

pub const u_strToUTF8: UStrToUTF8Fn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("u_strToUTF8_{d}", .{icu_ver})
    else
        "u_strToUTF8";
    break :blk @extern(UStrToUTF8Fn, .{ .name = name });
};

pub const utrans_openU: UtransOpenUFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("utrans_openU_{d}", .{icu_ver})
    else
        "utrans_openU";
    break :blk @extern(UtransOpenUFn, .{ .name = name });
};

pub const utrans_close: UtransCloseFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("utrans_close_{d}", .{icu_ver})
    else
        "utrans_close";
    break :blk @extern(UtransCloseFn, .{ .name = name });
};

pub const utrans_clone: UtransCloneFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("utrans_clone_{d}", .{icu_ver})
    else
        "utrans_clone";
    break :blk @extern(UtransCloneFn, .{ .name = name });
};

pub const utrans_transUChars: UtransTransUCharsFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("utrans_transUChars_{d}", .{icu_ver})
    else
        "utrans_transUChars";
    break :blk @extern(UtransTransUCharsFn, .{ .name = name });
};

pub const uloc_getLanguage: UlocGetLanguageFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("uloc_getLanguage_{d}", .{icu_ver})
    else
        "uloc_getLanguage";
    break :blk @extern(UlocGetLanguageFn, .{ .name = name });
};

pub const uloc_getAvailable: UlocGetAvailableFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("uloc_getAvailable_{d}", .{icu_ver})
    else
        "uloc_getAvailable";
    break :blk @extern(UlocGetAvailableFn, .{ .name = name });
};

pub const uloc_countAvailable: UlocCountAvailableFn = blk: {
    const name = if (icu_ver > 0)
        std.fmt.comptimePrint("uloc_countAvailable_{d}", .{icu_ver})
    else
        "uloc_countAvailable";
    break :blk @extern(UlocCountAvailableFn, .{ .name = name });
};
