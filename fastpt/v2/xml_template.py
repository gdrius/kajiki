import re
from collections import defaultdict
from cStringIO import StringIO
from xml import sax
from htmllib import HTMLParser
from xml.dom import minidom as dom

from . import ir
from . import template
from .markup_template import QDIRECTIVES, QDIRECTIVES_DICT

_pattern = r'''
\$(?:
    (?P<expr_escaped>\$) |      # Escape $$
    (?P<expr_named>[_a-z][_a-z0-9.]*) | # $foo.bar
    {(?P<expr_braced>) | # ${....
    (?P<expr_invalid>)
)'''
_re_pattern = re.compile(_pattern, re.VERBOSE | re.IGNORECASE|re.MULTILINE)

def XMLTemplate(
    source=None,
    filename=None):
    if source is None:
        source = open(filename).read()
    if filename is None:
        filename = '<string>'
    doc = _Parser(filename, source).parse()
    expand(doc)
    ir_ = _Compiler(filename, doc).compile()
    return template.from_ir(ir_)

class _Compiler(object):

    def __init__(self, filename, doc, mode='xml'):
        self.filename = filename
        self.doc = doc
        self.mode = mode
        self.functions = defaultdict(list)
        self.functions['__call__()'] = []
        self.mod_py = []
        self.in_def = False
        self.is_child = False

    def compile(self):
        body = list(self._compile_node(self.doc.firstChild))
        self.functions['__call__()'] = body
        defs = [ ir.DefNode(k, *v) for k,v in self.functions.iteritems() ]
        return ir.TemplateNode(self.mod_py, defs)


    def _compile_node(self, node):
        if isinstance(node, dom.Comment):
            return self._compile_comment(node)
        elif isinstance(node, dom.Text):
            return self._compile_text(node)
        elif node.tagName.startswith('py:'):
            # Handle directives
            compiler = getattr(self, '_compile_%s' % node.tagName.split(':')[-1])
            return compiler(node)
        elif isinstance(node, dom.ProcessingInstruction):
            return self._compile_pi(node)
        elif self.mode == 'xml':
            return self._compile_xml(node)
        else:
            return self._compile_html(node)

    def _compile_xml(self, node):
        yield ir.TextNode('<%s ' % node.tagName)
        for k,v in node.attributes.items():
            if k.startswith('py:'):
                raise NotImplemented, '_compile_attr(%s)' % k
            yield ir.AttrNode(k, list(self._compile_text(v)))
        if node.childNodes:
            yield ir.TextNode('>')
            for cn in node.childNodes:
                for x in self._compile_node(cn):
                    yield x
            yield ir.TextNode('</%s>' % node.tagName)
        else:
            yield ir.TextNode('/>')

    def _compile_text(self, node):
        tc = _TextCompiler(self.filename, node.data, node.lineno)
        for x in tc:
            yield x

class _TextCompiler(object):

    def __init__(self, filename, source, lineno):
        self.filename = filename
        self.source = source
        self.orig_lineno = lineno
        self.lineno = 0
        self.pos = 0
        
    def text(self, text):
        node = ir.TextNode(text)
        node.lineno = self.real_lineno
        self.lineno += text.count('\n')
        return node

    def expr(self, text):
        node = ir.ExprNode(text)
        node.lineno = self.real_lineno
        self.lineno += text.count('\n')
        return node

    @property
    def real_lineno(self):
        return self.orig_lineno + self.lineno

    def __iter__(self):
        source = self.source
        for mo in _re_pattern.finditer(source):
            start = mo.start()
            if start > self.pos:
                yield self.text(source[self.pos:start])
            self.pos = start
            groups = mo.groupdict()
            if groups['expr_braced'] is not None:
                self.pos = mo.end()
                yield self._get_braced_expr()
            elif groups['expr_named'] is not None:
                self.pos = mo.end()
                yield self.expr(groups['expr_named'])
            else:
                msg = 'Syntax error %s:%s' % (self.filename, self.real_lineno)
                for i, line in enumerate(self.source.splitlines()):
                    print '%3d %s' % (i+1, line)
                print msg
                assert False, groups

    def _get_braced_expr(self):
        try:
            compile(self.source[self.pos:], '', 'eval')
        except SyntaxError, se:
            end = se.offset+self.pos
            text = self.source[self.pos:end-1]
            self.pos = end
            return self.expr(text)
    
class _Parser(sax.ContentHandler):

    def __init__(self, filename, source):
        self._filename = filename
        self._source = source
        self._doc = None
        self._els = []

    def parse(self):
        self._parser = parser = sax.make_parser()
        parser.setFeature(sax.handler.feature_external_pes, False)
        parser.setFeature(sax.handler.feature_external_ges, False)
        parser.setFeature(sax.handler.feature_namespaces, False)
        parser.setProperty(sax.handler.property_lexical_handler, self)
        parser.setContentHandler(self)
        parser.parse(StringIO(self._source))
        return self._doc

    ## ContentHandler implementation
    def startDocument(self):
        self._doc = dom.Document()
        self._els.append(self._doc)

    def startElement(self, name, attrs):
        el = self._doc.createElement(name)
        el.lineno = self._parser.getLineNumber()
        for k,v in attrs.items():
            el.setAttribute(k,v)
        self._els[-1].appendChild(el)
        self._els.append(el)

    def endElement(self, name):
        popped = self._els.pop()
        assert name == popped.tagName

    def characters(self, content):
        node = self._doc.createTextNode(content)
        node.lineno = self._parser.getLineNumber()
        self._els[-1].appendChild(node)

    def processingInstruction(self, target, data):
        node = self._doc.createProcessingInstruction(target, data)
        node.lineno = self._parser.getLineNumber()
        self._els[-1].appendChild(node)

    def skippedEntity(self, name):
        content = unicode(HTMLParser.entitydefs[name], 'latin-1')
        return self.characters(content)

    def startElementNS(self, name, qname, attrs): # pragma no cover
        raise NotImplementedError, 'startElementNS'

    def endElementNS(self, name, qname):# pragma no cover
        raise NotImplementedError, 'startElementNS'

    def startPrefixMapping(self, prefix, uri):# pragma no cover
        raise NotImplemented, 'startPrefixMapping'

    def endPrefixMapping(self, prefix):# pragma no cover
        raise NotImplemented, 'endPrefixMapping'

    # LexicalHandler implementation
    def comment(self, text):
        node = self._doc.createComment(text)
        node.lineno = self._parser.getLineNumber()
        self._els[-1].appendChild(node)

    def startCDATA(self): pass
    def endCDATA(self): pass
    def startDTD(self, name, pubid, sysid): pass
    def endDTD(self): pass

def expand(tree, parent=None):
    if isinstance(tree, dom.Document):
        expand(tree.firstChild, tree)
        return tree
    if not isinstance(getattr(tree, 'tagName', None), basestring):
        return tree
    if tree.tagName in QDIRECTIVES_DICT:
        tree.setAttribute(
            tree.tag,
            tree.getAttribute(QDIRECTIVES_DICT[tree.tag]))
        tree.tagName = 'py:nop'
    for directive, attr in QDIRECTIVES:
        if not tree.hasAttribute(directive): continue
        value = tree.getAttribute(directive)
        tree.removeAttribute(directive)
        # nsmap = (parent is not None) and parent.nsmap or tree.nsmap
        el = tree.ownerDocument.createElement(directive)
        el.lineno = tree.lineno
        if attr:
            el.setAttribute(attr, value)
        # el.setsourceline = tree.sourceline
        if parent is None:
            tree.parentNode.replaceChild(newChild=el, oldChild=tree)
        else:
            parent.replaceChild(newChild=el, oldChild=tree)
        el.appendChild(tree)
        expand(tree, el)
        return el
    for child in tree.childNodes:
        expand(child, tree)
    return tree

