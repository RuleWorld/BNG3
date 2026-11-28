import re
import sys
import xml.etree.ElementTree as ET


_UNSAFE_XML_DECL_RE = re.compile(r"<!(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_RDF_RESOURCE_ATTR = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"


def walk(parent, outFile, level, database):  # [1]
    for node in list(parent):
        printLevel(outFile, level)
        for attrName, attrValue in node.attrib.items():
            printLevel(outFile, level + 2)
            if attrName in ("rdf:resource", _RDF_RESOURCE_ATTR):
                database.append(attrValue)

        content = []  # [3]
        if node.text:
            content.append(node.text)
        if content:
            _strContent = " ".join(content)
            printLevel(outFile, level)
        walk(node, outFile, level + 1, database)


def printLevel(outFile, level):
    for idx in range(level):
        # outFile.write('    ')
        pass


# [5]
def parseAnnotation(XMLString):
    outFile = ""
    if XMLString == "":
        return []
    if _UNSAFE_XML_DECL_RE.search(XMLString):
        raise ValueError("XML DOCTYPE/ENTITY declarations are not allowed in annotations")
    rootNode = ET.fromstring(XMLString)
    level = 0
    database = []
    # Also inspect attributes on rootNode itself if it carries rdf:resource.
    for attrName, attrValue in rootNode.attrib.items():
        if attrName in ("rdf:resource", _RDF_RESOURCE_ATTR):
            database.append(attrValue)
    walk(rootNode, outFile, level, database)
    return database


def main():
    args = sys.argv[1:]
    if len(args) != 1:
        print("usage: python test.py infile.xml")
        sys.exit(-1)
    print(parseAnnotation(args[0]))


if __name__ == "__main__":
    main()
