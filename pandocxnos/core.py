# Copyright 2015-2019 Thomas J. Duck.
# All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""core.py: library code for the pandoc-fignos/eqnos/tablenos filters.

Overview
--------

Below is a short summary of what is available.  More details are
given in the function docstrings.

#### Globals ####

  * `STRTYPES` - a tuple of string types for this python version
  * `STDIN`/`STDOUT`/`STDERR` - streams for use with pandoc

#### Utility functions ####

  * `init()` - Determines and returns the pandoc version
  * `check_bool()` - Checks that a value is boolean
  * `get_meta()` - Retrieves variables from a document's metadata
  * `add_to_header_includes()` - Adds to header-includes in metadata
  * `cleveref_required()` - True if cleveref is required, False otherwise

#### Element list functions ####

  * `quotify()` - Changes Quoted elements to quoted strings
  * `dollarfy()` - Changes Math elements to dollared strings
  * `extract_attrs()` - Extracts attribute strings

#### Actions and their factory functions ####

  * `join_strings()` - Joins adjacent strings in an element list
  * `repair_refs()` - Repairs broken Cite elements in a document
  * `process_refs_factory()` - Makes functions that process references
  * `replace_refs_factory()` - Makes functions that replace refs with
                               format-specific content
  * `attach_attrs_factory()` - Makes functions that attach attributes
                               to elements
  * `detach_attrs_factory()` - Makes functions that detach attributes
                               from elements
  * `insert_secnos_factory()` - Makes functions that insert section
                                numbers into attributes
  * `insert_rawblocks_factory()` - Makes function to insert
                                   non-duplicate Raw Block elements.
"""


__version__ = '2.0.0b5'


import os
import sys
import io
import subprocess
import re
import textwrap
import functools
import copy

import psutil

from pandocfilters import Str, Space, Math, RawInline, RawBlock, Link, Span
from pandocfilters import walk, stringify
from pandocfilters import elt as _elt

from .pandocattributes import PandocAttributes


# pylint: disable=too-many-lines


#=============================================================================
# Globals

# Python has different string types depending on the python version.  We must
# be able to identify them both.
# pylint: disable=undefined-variable
STRTYPES = (str,) if sys.version_info > (3,) else (str, unicode)

# Pandoc uses UTF-8 for both input and output; so must its filters.  This is
# handled differently depending on the python version.
if sys.version_info > (3,):
    # Py3 strings are unicode: https://docs.python.org/3.5/howto/unicode.html.
    # Character encoding/decoding is performed automatically at stream
    # interfaces: https://stackoverflow.com/questions/16549332/.
    # Set it to UTF-8 for all streams.
    STDIN = io.TextIOWrapper(sys.stdin.buffer, 'utf-8', 'strict')
    STDOUT = io.TextIOWrapper(sys.stdout.buffer, 'utf-8', 'strict')
    STDERR = io.TextIOWrapper(sys.stderr.buffer, 'utf-8', 'strict')
else:
    # Py2 strings are ASCII bytes.  Encoding/decoding is handled separately.
    # See: https://docs.python.org/2/howto/unicode.html.
    STDIN = sys.stdin
    STDOUT = sys.stdout
    STDERR = sys.stdout

# Flags that the cleveref package is needed
_cleveref_flag = False  # pylint: disable=invalid-name

# pylint: disable=invalid-name
sec = 0  # Used to track section numbers


#=============================================================================
# Decorators

# _repeat() ------------------------------------------------------------------

# The _repeat decorator repeats a call until something other than None is
# returned.  Functions that must return None should be broken into parts.
# See, for example, join_strings().

def _repeat(func):
    """Repeats func(...) call until something other than None is returned."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        """Repeats the call until True is returned."""
        ret = None
        while ret is None:
            ret = func(*args, **kwargs)
        return ret
    return wrapper


#=============================================================================
# Utility functions

# init() ---------------------------------------------------------------------

_PANDOCVERSION = None  # A string giving the pandoc version

# pylint: disable=too-many-branches
def init(pandocversion=None, doc=None):
    """Sets or determines the pandoc version.  This must be called.

    The pandoc version is needed for multi-version support.
    See: https://github.com/jgm/pandoc/issues/2640

    Returns the pandoc version."""

    # This requires some care because we can't be sure that a call to 'pandoc'
    # will work.  It could be 'pandoc-1.17.0.2' or some other name.  Try
    # checking the parent process first, and only make a call to 'pandoc' as
    # a last resort.

    global _PANDOCVERSION  # pylint: disable=global-statement

    pattern = re.compile(r'^[1-2]\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?$')

    if 'PANDOC_VERSION' in os.environ:  # Available for pandoc >= 1.19.1
        pandocversion = str(os.environ['PANDOC_VERSION'])

    if pandocversion is not None:
        # Test the result and if it is OK then store it in _PANDOCVERSION
        if pattern.match(pandocversion):
            _PANDOCVERSION = pandocversion
            return _PANDOCVERSION
        msg = 'Cannot understand pandocversion=%s'%pandocversion
        raise RuntimeError(msg)

    if doc is not None:
        if 'pandoc-api-version' in doc:
            # This could be either 1.18 or 1.19; there is no way to
            # distinguish them (but there isn't a use case in pandoc-fignos
            # and friends where it matters)
            _PANDOCVERSION = '1.18'
            return _PANDOCVERSION

    # Get the command
    try:  # Get the path for the parent process
        if os.name == 'nt':
            # psutil appears to work differently for windows
            command = psutil.Process(os.getpid()).parent().parent().exe()
        else:
            command = psutil.Process(os.getpid()).parent().exe()
        if not os.path.basename(command).startswith('pandoc'):
            raise RuntimeError('pandoc not found')
    except:  # pylint: disable=bare-except
        # Call whatever pandoc is available and hope for the best
        command = 'pandoc'

    # Make the call
    try:
        # Get the version number and confirm it conforms to expectations
        output = subprocess.check_output([command, '-v'])
        line = output.decode('utf-8').split('\n')[0]
        pandocversion = line.split(' ')[-1].strip()
    except: # pylint: disable=bare-except
        pandocversion = ''

    # Test the result and if it is OK then store it in _PANDOCVERSION
    if pattern.match(pandocversion):
        _PANDOCVERSION = pandocversion

    if _PANDOCVERSION is None:
        msg = textwrap.dedent("""\
            Cannot determine pandoc version.  Please file an issue at
            https://github.com/tomduck/pandocxnos/issues.""")
        raise RuntimeError(msg)

    return _PANDOCVERSION


# check_bool() ---------------------------------------------------------------

def check_bool(v):
    """Checks that metadata value is boolean.  Returns the value or
    raises an exception."""
    if not isinstance(v, bool):
        msg = 'Metadata boolean values must be one of the following: ' \
              'true, True, TRUE, false, False, FALSE. ' \
              'As of pandoc 2.2.2, the following are not allowed: ' \
              'On, Off.'
        raise ValueError(msg)
    return v


# get_meta() -----------------------------------------------------------------

# Metadata json depends upon whether or not the variables were defined on the
# command line or in a document.  The get_meta() function makes no
# distinction.

def get_meta(meta, name):
    """Retrieves the metadata variable 'name' from the 'meta' dict."""
    assert name in meta
    data = meta[name]

    if data['t'] in ['MetaString', 'MetaBool']:
        return data['c']
    if data['t'] == 'MetaInlines':
        # Handle bug in pandoc 2.2.3 and 2.2.3.1: Return boolean value rather
        # than strings, as appropriate.
        if len(data['c']) == 1 and data['c'][0]['t'] == 'Str':
            if data['c'][0]['c'] in ['true', 'True', 'TRUE']:
                return True
            if data['c'][0]['c'] in ['false', 'False', 'FALSE']:
                return False
        return stringify(data['c'])
    if data['t'] == 'MetaList':
        return [stringify(v['c']) for v in data['c']]
    if data['t'] == 'MetaMap':
        ret = {}
        for key in data['c']:
            ret[key] = stringify(data['c'][key])
        return ret
    raise RuntimeError("Could not understand metadata variable '%s'." % name)


# elt() ----------------------------------------------------------------------

def elt(eltType, numargs):  # pylint: disable=invalid-name
    """Returns Element(*value) to create pandoc json elements.

    This should be used in place of pandocfilters.elt().  This version
    ensures that the content is stored in a list, not a tuple.
    """
    def Element(*value):  # pylint: disable=invalid-name
        """Creates an element."""
        el = _elt(eltType, numargs)(*value)
        if isinstance(el['c'], tuple):
            el['c'] = list(el['c'])  # The content should be a list, not tuple
        return el
    return Element

Cite = elt('Cite', 2)  # pylint: disable=invalid-name

def _getel(key, value):
    """Returns an element given a key and value."""
    if key in ['HorizontalRule', 'Null']:
        return elt(key, 0)()
    if key in ['Plain', 'Para', 'BlockQuote', 'BulletList',
               'DefinitionList', 'HorizontalRule', 'Null']:
        return elt(key, 1)(value)
    return elt(key, len(value))(*value)


# add_to_header_includes() ------------------------------------------------

# WARNING: Pandoc's --include-in-header option overrides the header-includes
# meta variable in post-filter processing.  This owing to a design decision
# in pandoc.  See https://github.com/jgm/pandoc/issues/3139.

def add_to_header_includes(meta, fmt, block, warninglevel, regex=None):
    """Adds block to header-includes in metadata."""
    # If pattern is found in the meta-includes then bail out
    if regex and 'header-includes' in meta:
        pattern = re.compile(regex)
        if pattern.search(str(meta['header-includes'])):
            return
    # Create the rawblock and install it in the header-includes
    block = textwrap.dedent(block)
    rawblock = {'t': 'RawBlock', 'c': [fmt, block]}
    metablocks = {'t': 'MetaBlocks', 'c': [rawblock]}
    if 'header-includes' not in meta:
        meta['header-includes'] = metablocks
    elif meta['header-includes']['t'] in ['MetaBlocks', 'MetaInlines']:
        meta['header-includes'] = \
          {'t': 'MetaList', 'c': [meta['header-includes'], metablocks]}
    elif meta['header-includes']['t'] == 'MetaList':
        meta['header-includes']['c'].append(metablocks)
    else:
        msg = textwrap.dedent("""\
            header-includes metadata cannot be parsed:

            %s
            """ % str(meta['header-includes']))
        raise RuntimeError(msg)
    # Print the block to stderr at warning level 2
    if warninglevel == 2:
        if hasattr(textwrap, 'indent'):
            STDERR.write(textwrap.indent(block, '    '))
        else:
            STDERR.write('\n'.join('    ' + line for line in block.split('\n')))
            STDERR.flush()


# cleveref_required() --------------------------------------------------------

def cleveref_required():
    """Returns True if the cleveref usage was found during xnos processing,
    False otherwise."""
    return _cleveref_flag


#=============================================================================
# Element list functions

# quotify() ------------------------------------------------------------------

def quotify(x):
    """Replaces Quoted elements in element list 'x' with quoted strings.

    Pandoc uses the Quoted element in its json when --smart is enabled.
    Output to TeX/pdf automatically triggers --smart.

    stringify() ignores Quoted elements.  Use quotify() first to replace
    Quoted elements in 'x' with quoted strings.  'x' should be a deep copy so
    that the underlying document is left untouched.

    Returns x."""

    def _quotify(key, value, fmt, meta):  # pylint: disable=unused-argument
        """Replaced Quoted elements with quoted strings."""
        if key == 'Quoted':
            ret = []
            quote = '"' if value[0]['t'] == 'DoubleQuote' else "'"
            if value[1][0]['t'] == 'Str':
                value[1][0]['c'] = quote + value[1][0]['c']
            else:
                ret.append(Str(quote))

            if value[1][-1]['t'] == 'Str':
                value[1][-1]['c'] = value[1][-1]['c'] + quote
                ret += value[1]
            else:
                ret += value[1] + [Str(quote)]
            return ret
        return None

    return walk(walk(x, _quotify, '', {}), join_strings, '', {})


# dollarfy() -----------------------------------------------------------------

def dollarfy(x):
    """Replaces Math elements in element list 'x' with a $-enclosed string.

    stringify() passes through TeX math.  Use dollarfy(x) first to replace
    Math elements with math strings set in dollars.  'x' should be a deep copy
    so that the underlying document is left untouched.

    Returns 'x'."""

    def _dollarfy(key, value, fmt, meta):  # pylint: disable=unused-argument
        """Replaces Math elements"""
        if key == 'Math':
            return Str('$' + value[1] + '$')
        return None

    return walk(x, _dollarfy, '', {})


# extract_attrs() ------------------------------------------------------------

def extract_attrs(x, n):
    """Extracts attributes from element list 'x' beginning at index 'n'.

    The elements encapsulating the attributes (typically a series of Str and
    Space elements) are removed from 'x'.  Items before index 'n' are left
    unchanged.

    Returns the attributes.  A ValueError is raised if attributes aren't
    found.  An IndexError is raised if the index 'n' is out of range."""

    # Check for the start of the attributes string
    if not (x[n]['t'] == 'Str' and x[n]['c'].startswith('{')):
        raise ValueError('Attributes not found.')

    # It starts with {, so this *may* be an attributes list.  Search for where
    # the attributes end.  Do not consider } in quoted elements.

    seq = []          # A sequence of saved values
    quotechar = None  # Used to keep track of quotes in strings
    flag = False      # Flags that an attributes list was found
    i = 0             # Initialization

    for i, v in enumerate(x[n:]):  # Scan through the list
        if v and v['t'] == 'Str':
            # Scan for } outside of a quote
            for j, c in enumerate(v['c']):
                if c == quotechar:  # This is an end quote
                    quotechar = None
                elif c in ['"', "'"]:  # This is an open quote
                    quotechar = c
                elif c == '}' and quotechar is None:  # The attributes end here
                    # Split the string at the } and save the pieces
                    head, tail = v['c'][:j+1], v['c'][j+1:]
                    x[n+i] = copy.deepcopy(v)
                    x[n+i]['c'] = tail
                    v['c'] = head
                    flag = True
                    break
        seq.append(v)
        if flag:
            break

    if flag:  # Attributes string was found, so process it

        # Delete empty and extracted elements
        if x[n+i]['t'] == 'Str' and not x[n+i]['c']:
            del x[n+i]
        del x[n:n+i]

        # Process the attrs
        attrstr = stringify(dollarfy(quotify(seq))).strip()
        attrs = PandocAttributes(attrstr, 'markdown')

        # Remove extranneous quotes from kvs (this is absolutely necessary
        # or else html attributes can get ""double-quoted"")
        for k, v in attrs.items():  # pylint: disable=unused-variable
            if v[0] == v[-1] == '"' or v[0] == "'" == v[-1] == "'":
                attrs[k] = v[1:-1]

        # We're done
        return attrs

    # Attributes not found
    raise ValueError('Attributes not found.')


#=============================================================================
# Actions and their factory functions

# Actions act on pandoc json elements. The pandocfilters.walk() function
# applies the action to all json elements in a document.  A non-None return
# value by an action is used by walk() to replace an element.  It is often
# easier to modify or delete elements from element lists in place.


# join_strings() -------------------------------------------------------------

# Pandoc never produces adjacent Str elements.  They may, however, arise from
# processing by actions.  This function joins adjacent string elements found
# in Para and Plain blocks.

# The design pattern used by this function is repeated by other actions,
# below. Processing of an element list 'x' is relegated to a helper.  The
# helper processes the list iteratively.  Processing is restarted (through use
# of the _repeat() decorator) any time the element list is changed.  A value
# of None is returned by the outer function because all modifications are made
# in place.

@_repeat
def _join_strings(x, start=0):
    """Joins adjacent Str elements found in the element list 'x'."""
    for i in range(start, len(x)-1):  # Process successive pairs of elements
        if x[i]['t'] == 'Str' and x[i+1]['t'] == 'Str':
            x[i]['c'] += x[i+1]['c']
            del x[i+1]  # In-place deletion of element from list
            return None  # Forces processing to repeat
    return True  # Terminates processing

# pylint: disable=unused-argument
def join_strings(key, value, fmt=None, meta=None):
    """Joins adjacent Str elements in the 'value' list."""
    if key in ['Para', 'Plain']:
        _join_strings(value)
    elif key == 'Span':
        _join_strings(value, 1)
    elif key == 'Image':
        _join_strings(value[-2])
    elif key == 'Table':
        _join_strings(value[-5])


# repair_reference() ---------------------------------------------------------

# Reference regex.  This splits a reference into three components: the
# prefix, label and suffix.  e.g.:
# >>> _REF.match('xxx{+@fig:1}xxx').groups()
# ('xxx{+', 'fig:1', '}xxx').
_REF = re.compile(r'^((?:.*{)?[\*\+!]?)@([^:]*:[\w/-]+)(.*)')
def _is_broken_ref(key1, value1, key2, value2):
    """True if this is a broken reference; False otherwise."""
    # A link followed by a string may represent a broken reference
    if key1 != 'Link' or key2 != 'Str':
        return False
    # Assemble the parts
    n = 0 if _PANDOCVERSION < '1.16' else 1

    if isinstance(value1[n][0]['c'], list):
        # Occurs when there is quoted text in an actual link.  This is not
        # a broken link.  See Issue #1.
        return False

    s = value1[n][0]['c'] + value2
    # Return True if this matches the reference regex
    return bool(_REF.match(s))

@_repeat
def _repair_refs(x):
    """Performs the repair on the element list 'x'."""

    if not bool(_PANDOCVERSION):
        raise RuntimeError('Module uninitialized.  Please call init().')

    # Scan the element list x
    for i in range(len(x)-1):

        # Check for broken references
        if _is_broken_ref(x[i]['t'], x[i]['c'] if 'c' in x[i] else [],
                          x[i+1]['t'], x[i+1]['c'] if 'c' in x[i+1] else []):

            # Get the reference string
            n = 0 if _PANDOCVERSION < '1.16' else 1
            s = x[i]['c'][n][0]['c'] + x[i+1]['c']

            # Chop it into pieces.  Note that the prefix and suffix may be
            # parts of other broken references.
            prefix, label, suffix = _REF.match(s).groups()

            # Insert the suffix, label and prefix back into x.  Do it in this
            # order so that the indexing works.
            if suffix:
                x.insert(i+2, Str(suffix))
            x[i+1] = Cite(
                [{"citationId":label,
                  "citationPrefix":[],
                  "citationSuffix":[],
                  "citationNoteNum":0,
                  "citationMode":{"t":"AuthorInText", "c":[]},
                  "citationHash":0}],
                [Str('@' + label)])
            if prefix:
                if i > 0 and x[i-1]['t'] == 'Str':
                    x[i-1]['c'] = x[i-1]['c'] + prefix
                    del x[i]
                else:
                    x[i] = Str(prefix)
            else:
                del x[i]

            return None  # Forces processing to repeat

    return True  # Terminates processing

def repair_refs(key, value, fmt, meta):  # pylint: disable=unused-argument
    """Using "-f markdown+autolink_bare_uris" with pandoc < 1.18 splits a
    reference like "{@fig:one}" into email Link and Str elements.  This
    function replaces the mess with the Cite and Str elements we normally
    get.  Call this before any reference processing."""

    if _PANDOCVERSION >= '1.18':
        return

    # The problem spans multiple elements, and so can only be identified in
    # element lists.  Element lists are encapsulated in different ways.  We
    # must process them all.

    if key in ('Para', 'Plain'):
        _repair_refs(value)
    elif key == 'Image':
        _repair_refs(value[-2])
    elif key == 'Table':
        _repair_refs(value[-5])


# process_refs_factory() -----------------------------------------------------

def _extract_modifier(x, i, attrs):
    """Extracts the */+/! modifier in front of the Cite at index 'i' of the
    element list 'x'.  The modifier is stored in 'attrs'.
    Returns the updated index 'i'.
    """

    global _cleveref_flag  # pylint: disable=global-statement

    assert x[i]['t'] == 'Cite'

    # The modifier can either be found in the Cite prefix or in the Str
    # preceeding the Cite.  We must handle both cases.

    s = None            # The string containing the modifier
    modifier = None     # The modifier character
    has_prefix = False  # Flags that the Cite has a prefix
    if x[i]['c'][-2][0]['citationPrefix'] and \
      x[i]['c'][-2][0]['citationPrefix'][-1]['t'] == 'Str':
        # Modifier is in the last character of the citation prefix
        s = x[i]['c'][-2][0]['citationPrefix'][-1]['c']
        modifier = s[-1]
        has_prefix = True
    elif i > 0 and x[i-1]['t'] == 'Str':
        # Modifier is in the last character of the previous string
        s = x[i-1]['c']
        modifier = s[-1]
    if modifier:
        if not _cleveref_flag and modifier in ['*', '+']:
            _cleveref_flag = True
        if modifier in ['*', '+', '!']:
            attrs['modifier'] = modifier
            if len(s) > 1:  # Lop the modifier off of the string
                if has_prefix:
                    x[i]['c'][-2][0]['citationPrefix'][-1]['c'] = \
                        x[i]['c'][-2][0]['citationPrefix'][-1]['c'][:-1]
                else:
                    x[i-1]['c'] = x[i-1]['c'][:-1]
            # The element contains only the modifier; delete it
            elif has_prefix:
                del x[i]['c'][-2][0]['citationPrefix'][-1]
            else:
                del x[i-1]
                i -= 1

    return i

def _remove_brackets(x, i):
    """Removes curly brackets surrounding the Cite element at index 'i' in
    the element list 'x'.  It is assumed that the modifier has been
    extracted.  Empty strings are deleted from 'x'.
    Returns the updated index 'i'.
    """

    assert x[i]['t'] == 'Cite'

    # Look at the Cite prefix/suffix if available, otherwise the surrounding
    # text.
    if x[i]['c'][-2][0]['citationPrefix'] and \
      x[i]['c'][-2][0]['citationSuffix']:
        if x[i]['c'][-2][0]['citationPrefix'][-1]['t'] == \
          x[i]['c'][-2][0]['citationSuffix'][0]['t'] == 'Str':
            # The surrounding elements are strings; trim off curly brackets
            if x[i]['c'][-2][0]['citationPrefix'][-1]['c'].endswith('{') and \
              x[i]['c'][-2][0]['citationSuffix'][0]['c'].startswith('}'):
                if len(x[i]['c'][-2][0]['citationSuffix'][0]['c']) > 1:
                    x[i]['c'][-2][0]['citationSuffix'][0]['c'] = \
                      x[i]['c'][-2][0]['citationSuffix'][0]['c'][1:]
                else:
                    del x[i]['c'][-2][0]['citationSuffix'][0]
                if len(x[i]['c'][-2][0]['citationPrefix'][-1]['c']) > 1:
                    x[i]['c'][-2][0]['citationPrefix'][-1]['c'] = \
                      x[i]['c'][-2][0]['citationPrefix'][-1]['c'][:-1]
                else:
                    del x[i]['c'][-2][0]['citationPrefix'][-1]

    elif 0 < i < len(x)-1 and x[i-1]['t'] == x[i+1]['t'] == 'Str':
        # The surrounding elements are strings; trim off curly brackets
        if x[i-1]['c'].endswith('{') and x[i+1]['c'].startswith('}'):
            if len(x[i+1]['c']) > 1:
                x[i+1]['c'] = x[i+1]['c'][1:]
            else:
                del x[i+1]
            if len(x[i-1]['c']) > 1:
                x[i-1]['c'] = x[i-1]['c'][:-1]
            else:
                del x[i-1]
                return i-1

    return i

# Track bad labels so that we only warn about them once
badlabels = []

@_repeat
def _process_refs(name, x, patt, labels, warninglevel):
    """Strips surrounding curly braces and adds modifiers to the
    attributes of Cite elements.  Only references with labels in the 'labels'
    list are processed.  Repeats processing (via decorator) until no more
    unprocessed references are found."""

    # Scan the element list x for Cite elements with known labels
    for i, v in enumerate(x):
        if v['t'] == 'Cite' and len(v['c']) == 2:
            label = v['c'][-2][0]['citationId']
            if (patt and patt.match(label)) or label in labels:

                # A new reference was found; create some empty attrs for it
                attrs = PandocAttributes()

                # Extract the modifiers.  'attrs' is updated in place.
                # Element deletion could change the index of the Cite being
                # processed.
                i = _extract_modifier(x, i, attrs)

                # Remove surrounding brackets
                i = _remove_brackets(x, i)

                # Get the reference attributes
                try:
                    a = extract_attrs(x, i+1)
                    attrs.id = a.id
                    attrs.classes.extend(a.classes)
                    attrs.kvs.update(a.kvs)
                except (ValueError, IndexError):
                    pass  # None given

                # Attach the attributes
                v['c'].insert(0, attrs.list)

                # The element list may be changed
                if label in labels:
                    return None  # Forces processing to repeat via @_repeat

            if warninglevel and patt and \
              patt.match(label) and label not in badlabels:
                badlabels.append(label)
                msg = "\n%s: Bad reference: @%s.\n" % (name, label)
                STDERR.write(msg)

    return True  # Terminates processing in _repeat decorator

def process_refs_factory(name, patt, labels, warninglevel):
    """Returns process_refs(key, value, fmt, meta) action that processes
    text around a reference.  Only references with labels found in the
    'labels' list are processed.

    Consider the markdown "{+@fig:1}", which represents a reference to a
    figure. "@" denotes a reference, "fig:1" is the reference's label, and
    "+" is a modifier.  Valid modifiers are '+, '*' and '!'.

    This function strips curly braces and adds the modifiers to the attributes
    of Cite elements.  Cite attributes must be detached before the document is
    written to STDOUT because pandoc doesn't recognize them.  Alternatively,
    use an action from replace_refs_factory() to replace the references
    altogether.
    """

    # pylint: disable=unused-argument
    def process_refs(key, value, fmt, meta):
        """Processes references."""
        # References may occur in a variety of places; we must process them
        # all.

        if key in ['Para', 'Plain']:
            _process_refs(name, value, patt, labels, warninglevel)
        elif key == 'Image':
            _process_refs(name, value[-2], patt, labels, warninglevel)
        elif key == 'Table':
            _process_refs(name, value[-5], patt, labels, warninglevel)
        elif key == 'Span':
            _process_refs(name, value[-1], patt, labels, warninglevel)
        elif key == 'Emph':
            _process_refs(name, value, patt, labels, warninglevel)
        elif key == 'Strong':
            _process_refs(name, value, patt, labels, warninglevel)
        elif key == 'Cite':
            _process_refs(name, value[-2][0]['citationPrefix'], patt, labels,
                          warninglevel)
            _process_refs(name, value[-2][0]['citationSuffix'], patt, labels,
                          warninglevel)

    return process_refs


# replace_refs_factory() ------------------------------------------------------

# pylint: disable=too-many-arguments,unused-argument
def replace_refs_factory(references, use_cleveref_default, use_eqref,
                         plusname, starname, strip_id=False):
    """Returns replace_refs(key, value, fmt, meta) action that replaces
    references with format-specific content.  The content is determined using
    the 'references' dict, which maps each reference label to a
    [number/tag, secno] list (e.g.,
    { 'fig:1':[1, '1'], 'fig:2':[2,'1'], ...}).  If 'use_cleveref_default'
    is True, or if "modifier" in the reference's attributes is "+" or "*", then
    clever referencing is used; i.e., a name is placed in front of the number
    or string tag.  The 'plusname' and 'starname' lists give the singular
    and plural names for "+" and "*" clever references, respectively."""

    global _cleveref_flag  # pylint: disable=global-statement

    # Update global if clever referencing is required by default
    _cleveref_flag = _cleveref_flag or use_cleveref_default

    # pylint: disable=too-many-locals,unused-argument
    def _cite_replacement(key, value, fmt, meta):
        """Returns context-dependent content to replace a Cite element."""

        assert key == 'Cite'

        attrs = PandocAttributes(value[0], 'pandoc')

        nolink = attrs['nolink'].lower() == 'true' if 'nolink' in attrs \
          else False

        label = value[-2][0]['citationId']

        # Get the replacement value
        text = str(references[label][0]) if label in references else '??'

        # Choose between \Cref, \cref and \ref
        use_cleveref = attrs['modifier'] in ['*', '+'] \
          if 'modifier' in attrs else use_cleveref_default
        plus = attrs['modifier'] == '+' if 'modifier' in attrs \
          else use_cleveref_default
        name = plusname[0] if plus else starname[0]  # Name used by cref

        if strip_id:
            label = label.split(':')[1]

        # The replacement depends on the output format
        if fmt == 'latex':
            if use_cleveref:
                macro = r'\cref' if plus else r'\Cref'
                ret = RawInline('tex', r'%s{%s}'%(macro, label))
            elif use_eqref:
                ret = RawInline('tex', r'\eqref{%s}'%label)
            else:
                ret = RawInline('tex', r'\ref{%s}'%label)
            if nolink:  # https://tex.stackexchange.com/a/323919
                ret['c'][1] = \
                  r'{\protect\NoHyper' + ret['c'][1] + r'\protect\endNoHyper}'
        else:
            if use_eqref:
                text = '(' + text + ')'

            elem = Math({"t":"InlineMath", "c":[]}, text[1:-1]) \
              if text.startswith('$') and text.endswith('$') \
              else Str(text)

            if not nolink and label in references:
                prefix = 'ch%03d.xhtml' % references[label][1] \
                  if fmt in ['epub', 'epub2', 'epub3'] and \
                  references[label][1] else ''

                elem = elt('Link', 2)([elem],
                                      ['%s#%s' % (prefix, label), '']) \
                  if _PANDOCVERSION < '1.16' else \
                  Link(['', [], []], [elem], ['%s#%s' % (prefix, label), ''])

            ret = ([Str(name), Space()] if use_cleveref else []) + [elem]

        # If the Cite was square-bracketed then wrap everything in a span
        s = stringify(value[-1])
        # pandoc strips off intervening space between the prefix and the Cite;
        # we may have to add it back in
        prefix = value[-2][0]['citationPrefix']
        spacer = [Space()] \
          if prefix and not stringify(prefix).endswith(('{', '+', '*', '!')) \
          else []
        if s.startswith('[') and s.endswith(']'):
            els = value[-2][0]['citationPrefix'] + \
              spacer + ([ret] if fmt == 'latex' else ret) + \
              value[-2][0]['citationSuffix']
            # We don't yet know if there will be attributes, so leave them
            # as None.  This is fixed later when attributes are processed.
            ret = Span(None, els)

        return ret


    def replace_refs(key, value, fmt, meta):  # pylint: disable=unused-argument
        """Replaces references with format-specific content."""

        if key == 'Cite' and len(value) == 3:  # Replace the reference

            return _cite_replacement(key, value, fmt, meta)

        return None

    return replace_refs


# attach_attrs_factory() -----------------------------------------------------

# pylint: disable=redefined-outer-name
def attach_attrs_factory(name, f, warninglevel, extract_attrs=extract_attrs,
                         allow_space=False, replace=False):
    """Returns attach_attrs(key, value, fmt, meta) action that reads and
    attaches attributes to unattributed elements generated by the
    pandocfilters function f (e.g. pandocfilters.Math, etc).

    The extract_attrs() function should read and return the attributes and
    raise a ValueError or IndexError if attributes are not found.
    """

    # Get the name of the element from the function
    elname = f.__closure__[0].cell_contents

    @_repeat
    def _attach_attrs(x):
        """Extracts and attaches the attributes."""
        for i, v in enumerate(x):
            if v and v['t'] == elname:  # Find where the attributes start
                n = i+1
                if allow_space and n < len(x) and x[n]['t'] == 'Space':
                    n += 1
                try:  # Extract the attributes
                    attrs = extract_attrs(x, n)
                    if attrs.parse_failed and warninglevel:
                        msg = textwrap.dedent("""\
                            %s: Malformed attributes:
                            %s
                        """ % (name, attrs.attrstr))
                        STDERR.write('\n')
                        STDERR.write(msg)
                        STDERR.write('\n')

                    if replace:
                        x[i]['c'][0] = attrs.list
                    else:
                        x[i]['c'].insert(0, attrs.list)
                except (ValueError, IndexError):
                    if v['t'] == 'Span' and v['c'][0] is None:
                        # We changed this into a span before, but since
                        # the attributes are None (it was unattributed), it
                        # isn't a valid span.  Fix it.
                        els = x.pop(i)['c'][1]
                        els.insert(0, Str('['))
                        els.append(Str(']'))
                        for j, el in enumerate(els):
                            x.insert(i+j, el)
                        join_strings('Span', x)
                        return None
        return True

    def attach_attrs(key, value, fmt, meta):  # pylint: disable=unused-argument
        """Attaches attributes to an element."""
        if key in ['Para', 'Plain']:
            _attach_attrs(value)

            # Image: Add pandoc's figure marker if warranted
            if len(value) == 1 and value[0]['t'] == 'Image':
                value[0]['c'][-1][1] = 'fig:'

    return attach_attrs


# detach_attrs_factory() ------------------------------------------------------

def detach_attrs_factory(f, restore=False):
    """Returns detach_attrs(key, value, fmt, meta) action that detaches
    attributes attached to elements of type f (e.g. pandocfilters.Math, etc).
    Attributes provided natively by pandoc will be left as is."""

    # Get the name and standard length
    name = f.__closure__[0].cell_contents
    n = f.__closure__[1].cell_contents

    def detach_attrs(key, value, fmt, meta):  # pylint: disable=unused-argument
        """Detaches the attributes."""
        if key == name:
            assert len(value) <= n+1
            if len(value) == n+1:
                # Make sure value[0] represents attributes then delete
                assert len(value[0]) == 3
                assert isinstance(value[0][0], STRTYPES)
                assert isinstance(value[0][1], list)
                assert isinstance(value[0][2], list)
                attrs = PandocAttributes(value[0], 'pandoc')
                del value[0]
                if restore:
                    return [elt(key, *value), Str(attrs.to_markdown())]
        return None

    return detach_attrs


# insert_secnos_factory() ----------------------------------------------------

# pylint: disable=redefined-outer-name
def insert_secnos_factory(f):
    """Returns insert_secnos(key, value, fmt, meta) action that inserts
    section numbers into the attributes of elements of type f.
    """

    # Get the name and standard length
    name = f.__closure__[0].cell_contents
    n = f.__closure__[1].cell_contents

    def insert_secnos(key, value, fmt, meta):  # pylint: disable=unused-argument
        """Inserts section numbers into elements attributes."""

        global sec  # pylint: disable=global-statement

        if key == 'Header':
            if 'unnumbered' in value[1][1]:
                return
            if value[0] == 1:
                sec += 1
        if key == name:

            # Only insert if attributes are attached.  Images always have
            # attributes for pandoc >= 1.16.
            assert len(value) <= n+1
            if (name == 'Image' and len(value) == 3) or \
              len(value) == n+1:
                # Make sure value[0] represents attributes
                assert isinstance(value[0][0], STRTYPES)
                assert isinstance(value[0][1], list)
                assert isinstance(value[0][2], list)

                # Insert the section number into the attributes
                value[0][2].insert(0, ['secno', sec])

    return insert_secnos


# delete_secnos_factory() ----------------------------------------------------

# pylint: disable=redefined-outer-name
def delete_secnos_factory(f):
    """Returns delete_secnos(key, value, fmt, meta) action that deletes
    section numbers from the attributes of elements of type f.
    """

    # Get the name and standard length
    name = f.__closure__[0].cell_contents
    n = f.__closure__[1].cell_contents

    def delete_secnos(key, value, fmt, meta):  # pylint: disable=unused-argument
        """Deletes section numbers from elements attributes."""

        # Only delete if attributes are attached.   Images always have
        # attributes for pandoc >= 1.16.
        if key == name:
            assert len(value) <= n+1
            if (name == 'Image' and len(value) == 3) or len(value) == n+1:

                # Make sure value[0] represents attributes
                assert isinstance(value[0][0], STRTYPES)
                assert isinstance(value[0][1], list)
                assert isinstance(value[0][2], list)

                # Remove the secno attribute
                if value[0][2] and value[0][2][0][0] == 'secno':
                    del value[0][2][0]

    return delete_secnos


# install_rawblock_factory() -------------------------------------------------

def insert_rawblocks_factory(rawblocks):
    r"""Returns insert_rawblocks(key, value, fmt, meta) action that inserts
    non-duplicate RawBlock elements.
    """

    # pylint: disable=unused-argument
    def insert_rawblocks(key, value, fmt, meta):
        """Inserts non-duplicate RawBlock elements."""

        if not rawblocks:
            return None

        # Put the RawBlock elements in front of the first block element that
        # isn't also a RawBlock.

        if not key in ['Plain', 'Para', 'CodeBlock', 'RawBlock',
                       'BlockQuote', 'OrderedList', 'BulletList',
                       'DefinitionList', 'Header', 'HorizontalRule',
                       'Table', 'Div', 'Null']:
            return None

        if key == 'RawBlock':  # Remove duplicates
            rawblock = RawBlock(*value)
            if rawblock in rawblocks:
                rawblocks.remove(rawblock)
                return None

        if rawblocks:  # Insert blocks
            el = _getel(key, value)
            return [rawblocks.pop(0) for i in range(len(rawblocks))] + [el]

        return None

    return insert_rawblocks
