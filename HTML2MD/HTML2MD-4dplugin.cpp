#include "HTML2MD-4dplugin.h"
#include "html2md.h"
#include <string>
#include <vector>

void PluginMain(PA_long32 selector, PA_PluginParameters params) {
    switch(selector) {
        case 1: HTML2MD_command(params); break;
    }
}

static std::string utf16_to_utf8(const PA_Unichar* src, PA_long32 len) {
    std::string result;
    result.reserve(len);
    for (PA_long32 i = 0; i < len; i++) {
        unsigned int ch = src[i];
        if (ch >= 0xD800 && ch <= 0xDBFF && i + 1 < len) {
            unsigned int low = src[i + 1];
            if (low >= 0xDC00 && low <= 0xDFFF) { ch = 0x10000 + ((ch - 0xD800) << 10) + (low - 0xDC00); i++; }
        }
        if (ch < 0x80) result.push_back((char)ch);
        else if (ch < 0x800) { result.push_back((char)(0xC0 | (ch >> 6))); result.push_back((char)(0x80 | (ch & 0x3F))); }
        else if (ch < 0x10000) { result.push_back((char)(0xE0 | (ch >> 12))); result.push_back((char)(0x80 | ((ch >> 6) & 0x3F))); result.push_back((char)(0x80 | (ch & 0x3F))); }
        else { result.push_back((char)(0xF0 | (ch >> 18))); result.push_back((char)(0x80 | ((ch >> 12) & 0x3F))); result.push_back((char)(0x80 | ((ch >> 6) & 0x3F))); result.push_back((char)(0x80 | (ch & 0x3F))); }
    }
    return result;
}

static std::vector<PA_Unichar> utf8_to_utf16(const std::string& src) {
    std::vector<PA_Unichar> result;
    result.reserve(src.size());
    size_t i = 0;
    while (i < src.size()) {
        unsigned int ch = 0;
        unsigned char c = src[i];
        if (c < 0x80) { ch = c; i += 1; }
        else if (c < 0xE0) { ch = (c & 0x1F) << 6 | (src[i+1] & 0x3F); i += 2; }
        else if (c < 0xF0) { ch = (c & 0x0F) << 12 | (src[i+1] & 0x3F) << 6 | (src[i+2] & 0x3F); i += 3; }
        else { ch = (c & 0x07) << 18 | (src[i+1] & 0x3F) << 12 | (src[i+2] & 0x3F) << 6 | (src[i+3] & 0x3F); i += 4; }
        if (ch < 0x10000) result.push_back((PA_Unichar)ch);
        else { ch -= 0x10000; result.push_back((PA_Unichar)(0xD800 + (ch >> 10))); result.push_back((PA_Unichar)(0xDC00 + (ch & 0x3FF))); }
    }
    result.push_back(0);
    return result;
}

static void HTML2MD_command(PA_PluginParameters params) {
    PA_Unistring *htmlParam = PA_GetStringParameter(params, 1);
    PA_Unichar *htmlChars = PA_GetUnistring(htmlParam);
    PA_long32 htmlLen = PA_GetUnistringLength(htmlParam);
    std::string htmlUtf8 = utf16_to_utf8(htmlChars, htmlLen);
    std::string mdUtf8 = html2md::Convert(htmlUtf8);
    // Trim trailing whitespace
    while (!mdUtf8.empty() && (mdUtf8.back() == '\n' || mdUtf8.back() == '\r' || mdUtf8.back() == ' ')) mdUtf8.pop_back();
    std::vector<PA_Unichar> mdUtf16 = utf8_to_utf16(mdUtf8);
    PA_ReturnString(params, mdUtf16.data());
}
