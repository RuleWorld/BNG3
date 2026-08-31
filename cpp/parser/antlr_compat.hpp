#pragma once

// Windows SDK headers define ERROR as a numeric GDI status constant.  ANTLR4
// uses ERROR as an enum member, so the macro must be removed before any ANTLR
// runtime or generated parser header is included.  Some SDK/toolchain
// combinations also expose the older lowercase spelling.
#if defined(_WIN32)
#    if defined(ERROR)
#        undef ERROR
#    endif
#    if defined(constant)
#        undef constant
#    endif
#endif
