'''Text template syntax

Expressions:

${<python expr>}
$foo, $foo.bar

Tags:

%<tagname> .* \n
{%<tagname> %}

Escaping via backslash
\$ => $
\% => %
\{ => {
\\ => \

'''
import re
from collections import defaultdict
from itertools import chain

from fastpt import v2 as fpt
from fastpt.v2 import ir

_pattern = r'''
\$(?:
    (?P<expr_escaped>\$) |      # Escape $$
    (?P<expr_named>[_a-z][_a-z0-9.]*) | # $foo.bar
    {(?P<expr_braced>) | # ${....
    (?P<expr_invalid>)
) |
^\w*%(?:
    (?P<tag_bare>[a-z]+) | # %for, %end, etc.
    (?P<tag_bare_invalid>)
)|
{%(?:
    (?P<tag_begin>[a-z]+) | # {%for, {%end, etc.
    (?P<tag_begin_invalid>)
)|
^\w*{%-(?P<tag_begin_ljust>-[a-z]+)  # {%-for, {%-end, etc.
'''
_re_pattern = re.compile(_pattern, re.VERBOSE | re.IGNORECASE|re.MULTILINE)

_re_newline_join = re.compile(r'(?<!\\)\\\n')

def TextTemplate(
    source=None,
    filename=None):
    if source is None:
        source = open(filename).read()
    if filename is None:
        filename = '<string>'
    tokenizer = _Tokenizer(filename, source)
    ast = _Parser(tokenizer).parse()
    return fpt.template.from_ir(ast)

class _Parser(object):

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.functions = defaultdict(list)
        self.functions['__call__()'] = []
        self.iterator = iter(self.tokenizer)

    def parse(self):
        body = list(self._parse_body())
        self.functions['__call__()'] = body[:-1]
        return ir.TemplateNode(
            *[ ir.DefNode(k, *v) for k,v in self.functions.iteritems() ])

    def text(self, token):
        text = _re_newline_join.sub('', token.text)
        node = ir.TextNode(text)
        node.filename = token.filename
        node.lineno = token.lineno
        return node

    def expr(self, token):
        node = ir.ExprNode(token.text)
        node.filename = token.filename
        node.lineno = token.lineno
        return node

    def push_tok(self, token):
        self.iterator = chain([token], self.iterator)

    def _parse_body(self, *stoptags):
        while True:
            try:
                token = self.iterator.next()
                if isinstance(token, _Text):
                    yield self.text(token)
                elif isinstance(token, _Expr):
                    yield self.expr(token)
                elif isinstance(token, _Tag):
                    if token.tagname in stoptags:
                        yield token
                        break
                    parser = getattr(self, '_parse_%s' % token.tagname)
                    yield parser(token)
                else:
                    msg = 'Parse error: %r unexpected' % token
                    assert False, msg
            except StopIteration:
                yield None
                break

    def _parse_for(self, token):
        body = list(self._parse_body('end'))
        return ir.ForNode(token.body, *body[:-1])

    def _parse_switch(self, token):
        body = list(self._parse_body('end'))
        return ir.SwitchNode(token.body, *body[:-1])

    def _parse_case(self, token):
        body = list(self._parse_body('case', 'else', 'end'))
        stoptok = body[-1]
        self.push_tok(stoptok)
        return ir.CaseNode(token.body, *body[:-1])

    def _parse_else(self, token):
        body = list(self._parse_body('end'))
        stoptok = body[-1]
        self.push_tok(stoptok)
        return ir.ElseNode(*body[:-1])

class _Tokenizer(object):

    def __init__(self, filename, source):
        self.filename = filename
        self.source = source
        self.lineno = 1
        self.pos = 0

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
            elif groups['tag_bare'] is not None:
                self.pos = mo.end()
                yield self._get_tag_bare(groups['tag_bare'])
            elif groups['tag_begin'] is not None:
                self.pos = mo.end()
                yield self._get_tag(groups['tag_begin'])
            elif groups['tag_bare_invalid'] is not None:
                continue
            else:
                msg = 'Syntax error %s:%s' % (self.filename, self.lineno)
                for i, line in enumerate(self.source.splitlines()):
                    print '%3d %s' % (i+1, line)
                print msg
                assert False, groups
        if self.pos != len(source):
            yield self.text(source[self.pos:])

    def _get_pos(self):
        return self._pos
    def _set_pos(self, value):
        assert value >= getattr(self, '_pos', 0)
        self._pos = value
    pos = property(_get_pos, _set_pos)

    def text(self, text):
        self.lineno += text.count('\n')
        return _Text(self.filename, self.lineno, text)

    def expr(self, text):
        self.lineno += text.count('\n')
        return _Expr(self.filename, self.lineno, text)

    def tag(self, tagname, body):
        tag = _Tag(self.filename, self.lineno, tagname, body)
        self.lineno += tag.text.count('\n')
        return tag

    def _get_tag_bare(self, tagname):
        end = self.source.find('\n', self.pos)
        if end == -1:
            end = len(self.source)
        body = self.source[self.pos:end]
        self.lineno += 1
        self.pos = end+1
        return self.tag(tagname, body)

    def _get_tag(self, tagname):
        end = self.source.find('%}', self.pos)
        body = self.source[self.pos:end]
        self.pos = end+2
        return self.tag(tagname, body)

    def _get_braced_expr(self):
        try:
            compile(self.source[self.pos:], '', 'eval')
        except SyntaxError, se:
            end = se.offset+self.pos
            text = self.source[self.pos:end-1]
            self.pos = end
            return self.expr(text)
    
class _Token(object):
    def __init__(self, filename, lineno, text):
        self.filename = filename
        self.lineno = lineno
        self.text = text

    def __repr__(self):
        return '<%s %r>' % (
            self.__class__.__name__,
            self.text)

class _Expr(_Token): pass
class _Text(_Token): pass
class _Tag(_Token):
    def __init__(self, filename, lineno, tagname, body):
        self.tagname = tagname
        self.body = body
        text = tagname + ' ' + body
        super(_Tag, self).__init__(filename, lineno, text)
