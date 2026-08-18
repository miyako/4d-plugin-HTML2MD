//%attributes = {"invisible":true,"preemptive":"capable"}

ASSERT(HTML2MD("<h1>Hello</h1>")="# Hello")
ASSERT(HTML2MD("<p>Hello</p>")="Hello")
ASSERT(HTML2MD("<strong>bold</strong>")="**bold**")
ASSERT(HTML2MD("<em>italic</em>")="*italic*")
ASSERT(HTML2MD("")="")
