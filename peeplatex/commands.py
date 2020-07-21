import subprocess
import asyncio
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
from tempfile import NamedTemporaryFile
from operator import itemgetter

import yaml
import prompt_toolkit as pt

from . import refMgmt
from . import listPrint
from ._shared import *



#############################################################################
#### Functions which (generally) parse prompt input, perform error checking,
#### and dispatch to specialised methods. Some are smart enough to be called
#### from outside the prompt, too.

@_helpdeco
@_timedeco
def read(args=None, silent=False):
    """
    Usage: r[ead] [path_to_file]

    Reads a list of articles stored as a YAML file. If the argument is a
    directory, then attempts to read a file named db.yaml in the directory.

    This function is automatically called when PeepLaTeX first starts, using
    either the argument passed on the command-line, or with the user's current
    working directory.

    When a new database is read in, the references will be sorted by year. The
    undo history will also be cleared.

    ** Function details **
    Reads from a YAML file. Sets the global variables _g.articleList and
    _g.currentPath if successful.

    Arguments:
        args:   String, pathlib.Path object, or a list/tuple containing a string
                or Path object as the first item.
        silent: True to suppress output. Does not suppress errors.

    Returns:
        Return codes as defined in _ret.
    """
    # Argument parsing
    if isinstance(args, (list, tuple)):
        try:
            args = args[0]
        except IndexError:   # empty list or tuple
            args = Path.cwd()
    try:
        p = Path(args)
    except TypeError:   # not castable
        return _error("read: invalid argument '{}'".format(args))
    else:
        # if p is not an absolute path, we want to resolve it with respect
        # to _g.currentPath. If that is None, we fall back to Path.cwd().
        if not p.is_absolute():
            p = (_g.currentPath.parent if _g.currentPath is not None \
                 else Path.cwd()) / p

    # If it points to an existing directory, load db.yaml from there
    if p.is_dir() and p.exists():
        p = p / "db.yaml"
    # Expand tildes and relative paths
    fname = p.expanduser().resolve()
    # If it is the same file, don't bother loading it
    if fname == _g.currentPath:
        return _error("read: file {} already loaded".format(fname))

    # If there is an article list loaded, save it first!
    if _g.articleList and _g.currentPath and _g.changes != []:
        _g.changes = []
        write()
    elif _g.articleList and not _g.currentPath:
        # list was created from scratch
        return _error("read: current library has not been saved, cannot read a new list")

    # Check if the yaml file exists
    if not fname.exists():
        return _error("read: file {} not found".format(fname))

    # Read in the yaml file
    try:
        with open(fname, "r") as fp:
            if not silent:
                print("read: reading library {}... ".format(fname))
            try:
                # don't overwrite the global first...
                newArticles = list(yaml.safe_load_all(fp))
            except yaml.YAMLError:
                return _error("read: invalid YAML file {}".format(fname))
            if not silent:
                print("read: done")
    except FileNotFoundError:  # seems redundant, but ok
        return _error("read: file {} not found".format(fname))
    else:
        ### At this point no more errors are expected, we can set the globals.
        # Clear history.
        _clearHist()
        # Set articles.
        _g.articleList = newArticles
        # Backup the new article list before doing anything, but only if
        #  it's really a new article...
        if fname != _g.currentPath:
            _g.currentPath = fname
            backup()
        # Then sort the list in place (which will trigger autosave)
        sortArticleList()

    return _ret.SUCCESS


@_helpdeco
@_timedeco
def write(args=None, silent=False):
    """
    Usage: w[rite] [path_to_file]

    Writes the current database to a YAML file. If the argument is a directory,
    then writes to the file db.yaml in that directory. If the argument is not
    provided, then writes to the path of the currently loaded database.

    ** Function details **
    Writes to a YAML file.

    Arguments:
        args:   String, pathlib.Path object, or a list/tuple containing a string
                or Path object as the first item.
        silent: True to suppress output. Does not suppress errors.

    Returns:
        Return codes as defined in _ret.
    """
    ### Argument parsing
    # Convert to a pathlib.Path object regardless of the input
    if isinstance(args, (list, tuple)):
        try:
            args = args[0]
        except IndexError:   # empty list or tuple
            if _g.currentPath is not None:
                args = _g.currentPath
            else:
                return _error("write: no filename specified")
    if args is None:
        if _g.currentPath is not None:
            args = _g.currentPath
        else:
            return _error("write: no filename specified")
    try:
        fname = Path(args)
    except TypeError:  # not castable
        return _error("write: invalid argument '{}'".format(args))

    # Determine output location
    if fname.is_dir() and fname.exists():
        fname = fname / "db.yaml"

    # Write to the file
    try:
        with open(fname, "w") as fp:
            if not silent:
                print("write: writing current library to {}... ".format(fname))
            yaml.dump_all(_g.articleList, fp)
            if _g.currentPath is None:
                _g.currentPath = fname
            _g.changes = []
            if not silent:
                print("write: done")
    except FileNotFoundError:
        return _error("write: directory {} does not exist".format(fname.parent))

    return _ret.SUCCESS


@_helpdeco
@_timedeco
def listArticles(args=None, articles=None, refnos=None, maxAuth=5, type="long"):
    """
    Usage: l[ist] [refnos]

    Lists articles in the currently loaded database. If no further reference
    numbers are specified, lists all articles. Also prints information about
    whether the full text PDF and the SI are stored in the database.

    Reference numbers may be specified as a comma- or space-separated series of
    integers or ranges (low-high, inclusive). For example, 'l 41-43' lists
    articles 41 through 43. 'l 4, 9, 21-24' lists articles 4, 9, and 21 through
    24. 'all' can be used as a shortcut for every reference number.

    By default, if this is invoked with just 'l', the list of authors in each
    article is truncated such that it occupies at most 5 lines. This default
    behaviour can be overruled by specifying reference numbers, as described
    above. Thus, using 'l all' will print the entire list but with all authors.

    ** Function details **
    Prints a list of articles. This function essentially has two interfaces.

    The first interface is via the command-line, where 'args' is passed as a
    list of strings. This is parsed to give a list of reference numbers which
    should be printed.

    The second, more flexible, interface is for printing specific lists of
    articles, for example those which have been filtered by a search keyword.
    To use this, pass the lists 'articles' and 'refnos' as arguments. This is
    (usually) more suitable for use from other subroutines. An additional
    parameter 'type' can be used to control the verbosity.

    If one simply wants to print every article, then this can be most easily
    invoked as listArticles().

    Arguments:
        args:     List of command-line arguments. Passing this manually is not
                  recommended; instead, use the articles and refnos parameters.
        articles: List of articles to be printed. Defaults to _g.articleList.
        refnos:   List of refnos to be printed. Defaults to
                  range(1, len(articles) + 1).
                  The order of the two lists passed, articles and refnos, is
                  always preserved (using zip()).
        type:     'long' - prints every article.
                  'short' - prints the first two and last two articles.

    Returns:
        Return codes as defined in _ret.
    """

    # Interface 1: via command line
    if articles is None and refnos is None:
        arts = deepcopy(_g.articleList)
        l = len(arts)
        # If short mode is requested but the list is too short, go back to long mode
        if type == "short" and l <= 4:
            type == "long"
        # Exit if an empty list is provided
        if arts == []:
            return _error("listArticles: no articles found")

        # Parse reference numbers.
        # If it's short, then we don't need to do anything beyond picking those four
        if type == "short":
            refnos = [1, 2, l - 1, l]
        if type == "long":
            # By default print all references, otherwise fetch refnos.
            if args == []:
                refnos = range(1, l + 1)
            else:
                refnos = refMgmt.parseRefno(",".join(args))
            # Check the returned values
            if refnos is _ret.FAILURE or refnos == [] or any(r > l for r in refnos):
                return _error("listArticles: invalid "
                              "argument{} '{}' given".format(_p(args), " ".join(args)))
        # Pick out the desired references.
        # We have to do it at this stage before we calculate the field widths.
        arts = [arts[r - 1] for r in refnos]

    # Interface 2: via arguments 'articles' and 'refnos'
    else:
        arts = deepcopy(articles)
        l = len(arts)
        refnos = list(refnos)
        if l != len(refnos):
            return _error("listArticles: articles and refnos "
                          "have different lengths ({} and {})".format(l, len(refnos)))

    # Truncate authors if the list was called with just 'l' from command-line.
    if args == []:
        arts = [listPrint.truncateAuthors(a, maxAuth=5) for a in arts]
    # Always print PDF availability.
    printAvail = True

    # Get field sizes
    layout_str = "{0:<{1}}{2:{3}}{4:<{5}}{6:{7}}{8:{9}}"
    fss = listPrint.getFS(arts, refnos)
    number_fs, author_fs, year_fs, journal_fs, title_fs = fss

    # Print header
    listPrint.printListHead(layout_str, fss)

    # Print all article contents
    if type == "long":
        for r, a in zip(refnos, arts):
            listPrint.listOneArticle(r, a, layout_str, fss, printAvail)
        return _ret.SUCCESS
    elif type == "short":
        # refnos and arts have already been set correctly, so we can index from 0 to 3
        # don't print PDF availability.
        listPrint.listOneArticle(refnos[0], arts[0], layout_str, fss, False)
        listPrint.listOneArticle(refnos[1], arts[1], layout_str, fss, False)
        listPrint.printDots(layout_str, fss)
        listPrint.listOneArticle(refnos[2], arts[2], layout_str, fss, False)
        listPrint.listOneArticle(refnos[3], arts[3], layout_str, fss, False)
        return _ret.SUCCESS
    else:
        return _error("listArticles: invalid type '{}'".format(type))


@_helpdeco
@_timedeco
def openRef(args):
    """
    Usage: o[pen] refno[...] [formats]

    Opens the original text of one or more references.

    At least one refno must be specified. For more details about the format in
    which refnos are specified, type 'h list'.

    More than one format can be provided, separated by commas, spaces, or even
    by nothing at all. Available formats are:

        'pdf' or 'p' (default) - The full text of the article (as a PDF).
        'si'  or 's'           - The SI of the article (as a PDF).
        'web' or 'w'           - The website.

    If the PDFs are not present in the relevant folder, they can be added using
    the 'ap' command.

    ** Function details **
    This function doesn't have bells or whistles. It just opens references.
    This should only be invoked from the command-line. In the future we might
    consider letting it take other parameters for manual specification of
    refnos or formats, but for now, that's what this is.

    Arguments:
        args: List of command-line arguments.

    Returns:
        Return codes as defined in _ret.
    """
    if _g.articleList == []:
        return _error("openRef: no articles have been loaded")
    if args == []:
        return _error("openRef: no references selected")
    # Process args
    abbrevs = {"p": "pdf",
               "s": "si",
               "w": "web"}
    refnos, formats = refMgmt.parseRefnoFormat(args, abbrevs=abbrevs)

    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos) \
            or formats is _ret.FAILURE or any(f not in abbrevs for f in formats):
        return _error("openRef: invalid argument{} '{}' given".format(_p(args),
                                                                      " ".join(args)))
    # Default format
    if formats == []:
        formats = ['p']

    # Open the references
    drfs = ((_g.articleList[r - 1]["doi"], r, f) for r in refnos for f in formats)
    # open(1) is really fast, so it doesn't seem like this could be a problem unless we
    #  are opening tons and tons of references. But if it does then we may want to use
    #  some concurrency methods.
    yes, no = 0, 0
    for drf in drfs:
        c = refMgmt.openDOIType(*drf, _g.currentPath)
        if c == _ret.SUCCESS:
            _g.articleList[drf[1] - 1]["timeOpened"] = datetime.now(timezone.utc)
            yes += 1
        else:
            no += 1
    print("openRef: {} references opened, {} failed".format(yes, no))
    _g.changes += ["open"] * yes
    return _ret.SUCCESS


@_asynchelpdeco
@_timedeco
async def cite(args):
    """
    Usage: c[ite] refno[...] [formats]

    Provides a citation for one or more references. Also copies the citation
    text to the clipboard.

    At least one refno must be specified. For more details about the format in
    which refnos are specified, type 'h list'.

    More than one format can be provided, separated by commas, spaces, or even
    by nothing at all. Available formats are:

        'bib' or 'b' (default) - BibLaTeX. The article identifier is
                                 constructed by concatenating the first author,
                                 year, and journal.
        'markdown' or 'm'      - Markdown form of 'short' ACS style citation.
        'Markdown' or 'M'      - Markdown form of 'long' ACS style citation.
        'doi' or 'd'           - Just the DOI.

    ** Function details **
    This function doesn't have bells or whistles. It just cites references.
    This should only be invoked from the command-line. In the future we might
    consider letting it take other parameters for manual specification of
    refnos or formats, but for now, that's what this is.

    Copying to the clipboard is implemented in an asynchronous manner, which
    is nice.

    Arguments:
        args: List of command-line arguments.

    Returns:
        Return codes as defined in _ret.
    """
    if _g.articleList == []:
        return _error("cite: no articles have been loaded")
    if args == []:
        return _error("cite: no references selected")
    # Process args
    abbrevs = {"d": "doi",
               "b": "bib",
               "m": "markdown",
               "M": "Markdown",
               "w": "word"}
    refnos, formats = refMgmt.parseRefnoFormat(args, abbrevs=abbrevs)

    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos) \
            or formats is _ret.FAILURE or any(f not in abbrevs for f in formats):
        return _error("cite: invalid argument{} '{}' given".format(_p(args),
                                                                   " ".join(args)))
    # Default format = biblatex
    if formats == []:
        formats = ['b']

    sep = ""  # Need a newline between citations if there is more than one.
    afs = ((_g.articleList[r - 1], f) for r in refnos for f in formats)
    citation = ""
    for af in afs:
        citation += sep
        citation += refMgmt.MetadataToCitation(*af)
        if len(refnos) > 1 or len(formats) > 1:
            sep = "\n\n" if af[1] in "bMm" else "\n"
    print(citation)
    rval = await _copy(citation)
    return rval


@_helpdeco
@_timedeco
def editRef(args):
    """
    Usage: e[dit] refno[...]

    Directly edit the entries for one or more citations, using vim. To cancel
    any changes made, exit vim using :cq.

    At least one refno must be specified. For more details about the format in
    which refnos are specified, type 'h list'.

    ** Function details **
    This is a function which is only meant to be invoked from the command-line.

    Arguments:
        args: List of command-line arguments.

    Returns:
        Return codes as defined in _ret.
    """
    if _g.articleList == []:
        return _error("editRef: no articles have been loaded")
    if args == []:
        return _error("editRef: no references selected")

    # no formats to process; just refnos
    refnos = refMgmt.parseRefno(",".join(args))
    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos):
        return _error("editRef: invalid argument{} '{}' given".format(_p(args),
                                                                      " ".join(args)))

    # Construct the initial message
    articlesToEdit = []
    for r in refnos:
        articlesToEdit.append(deepcopy(_g.articleList[r - 1]))
    # Create and write data to temp file.
    # Suffix is needed so that vim syntax highlighting is enabled. :)
    fname = NamedTemporaryFile(suffix=".yaml").name
    with open(fname, 'wb') as fp:
        yaml.dump_all(articlesToEdit, fp, encoding=_g.gpe)
    # Open the file in vim. Vim's stdin and stdout need to be from/to a terminal.
    # This is already the case for stdin, but we need to set stdout manually.
    try:
        subprocess.run(["vim", fname], stdout=open('/dev/tty', 'wb'), check=True)
    except subprocess.CalledProcessError:   # e.g. :cq
        return _error("editRef: vim quit unexpectedly; no changes made")
    else:
        # Put the edited metadata back in the article list. If changes have been 
        #  made, increment _g.changes to trigger autosave.
        with open(fname, "r") as fp:
            try:
                editedArticles = list(yaml.safe_load_all(fp))
            except yaml.YAMLError:
                return _error("editRef: invalid YAML syntax")
            for (a, r) in zip(editedArticles, refnos):
                if _g.articleList[r - 1] != a:
                    _g.articleList[r - 1] = deepcopy(a)
                    _g.changes += ["edit"]
        return _ret.SUCCESS


@_asynchelpdeco
@_timedeco
async def addRef(args):
    """
    Usage: a[dd] DOI[...]

    Adds one or more DOIs to the reference list. Separate DOIs must be
    separated by spaces. After the reference is added, the list is sorted
    again using the currently active sorting method.

    Uses the Crossref API to obtain metadata about an article. Unfortunately,
    this isn't smart enough (yet) to get the PDF directly from the Internet.

    ** Function details **
    This should only be invoked via the command-line.

    Arguments:
        args: List of command-line arguments.

    Returns:
        A tuple, containing number of DOIs added and number of DOIs not added.
    """
    if args == []:
        return _error("addRef: no DOIs provided")
    yes = 0
    no = 0

    # Check if any are already in the library
    dois = []
    for doi in args:
        found = False
        for r, art in enumerate(_g.articleList, start=1):
            if doi == art["doi"]:
                found = True
                break
        if found:
            _error("addRef: DOI '{}' already in library.\n".format(doi) + \
                   "               Use 'u[pdate] {}' to refresh metadata.".format(r))
            no += 1
        else:
            dois.append(doi)
    if dois == []:
        return

    # create spinner
    prog = _progress(len(dois))
    spin = asyncio.create_task(_spinner("Fetching metadata", prog))

    # Perform asynchronous HTTP requests
    arts = []
    crefCoros = [refMgmt.DOIToMetadata(doi, _g.ahSession) for doi in dois]
    for coro in asyncio.as_completed(crefCoros):
        arts.append(await coro)
        prog.incr(1)
    # Kill spinner, and actually wait for it to be killed, otherwise
    # the output below gets messed up terribly
    spin.cancel()
    await asyncio.sleep(0)

    for a in arts:
        # Check for failure
        if a["title"] is None:
            _error("addRef: invalid DOI '{}'".format(a["doi"]))
            no += 1
            continue
        else:
            a["timeAdded"] = datetime.now(timezone.utc)
            a["timeOpened"] = datetime.now(timezone.utc)
            # Prompt user whether to accept the article
            refMgmt.diffArticles({}, a)
            msg = "addRef: accept new data (y/n)? ".format()
            style = pt.styles.Style.from_dict({"prompt": _g.ptBlue, "": _g.ptGreen})
            try:
                ans = await pt.PromptSession().prompt_async(msg, style=style)
            except (EOFError, KeyboardInterrupt):
                ans = "no"
            if ans.strip().lower() in ["", "y", "yes"]:
                _g.articleList.append(a)
                print("addRef: added DOI '{}'".format(doi))
                yes += 1
            else:
                print("addRef: DOI {} not added".format(doi))
                no += 1

    print("addRef: {} DOIs added, {} failed".format(yes, no))
    _g.changes += ["add"] * yes
    sortArticleList()
    return yes, no


@_helpdeco
@_timedeco
def sortArticleList(args=None):
    """
    Usage: so[rt] [mode]

    Sorts the currently loaded database. The key by which to sort can be
    passed as the only option. The available modes are:

        "year", "yja", or "y"     - first by year, then journal name, then
                                    first author surname
        "opened", "open", or "o"  - by the time last opened
        "added", "add", or "a"    - by the time added to the database

    If no key is used, then the current sorting mode is used. When loading
    an article, this will always be "year", but when calling 'so <key>', the
    requested key will be stored as the current sorting mode.

    By default, articles are sorted from oldest to newest, such that the most
    recent articles always appear at the bottom of the list (i.e. easiest to
    see). Reverse sort can be performed by capitalising the first letter of
    the key passed as a command-line argument, e.g. 'so Y' to sort from newest
    to oldest.

    ** Function details **
    This sorts the global list _g.articleList in-place. If no argument is
    passed, it uses _g.sortMode and _g.sortReverse as the sort arguments.

    If you want to sort a copy of a list without modifying it, you shoulduse
    sortCopyArticles().

    Arguments:
        args: list of command-line arguments

    Returns:
        Return codes as defined in _ret.
    """
    # Argument processing
    if args is None or args == [] or args[0] == "":
        mode, reverse = _g.sortMode, _g.sortReverse
    else:
        # Pick out capital letter, then convert to lowercase
        reverse = True if args[0][0].isupper() else False
        args[0] = args[0].lower()
        # Choose sorting mode
        if args[0] in ["y", "yja", "year"]:  # default
            mode = "yja"
        elif args[0] in ["o", "op", "ope", "open", "opened", "timeopened"]:
            mode = "timeOpened"
        elif args[0] in ["a", "ad", "add", "added", "timeadded"]:
            mode = "timeAdded"
        else:
            return _error("sortArticleList: invalid sort mode '{}' provided".format(args[0]))
        # Set the current sorting mode
        _g.sortMode, _g.sortReverse = mode, reverse
    if _g.articleList == []:
        return _error("sortArticleList: no articles have been loaded")

    # Sort in place
    _g.articleList.sort(key=_g.sortKey[mode], reverse=reverse)
    # Trigger autosave
    _g.changes += ["sort"]
    return _ret.SUCCESS


@_timedeco
def sortCopyArticles(articles=None, refnos=None, mode=None, reverse=None):
    """
    ** Function details **

    Sorts a list of articles and refnos by the given mode. This function makes
    a copy of the lists, so the original lists are not mutated. This is useful
    for generating input to listArticles(), which zips the two lists up before
    printing them.

    Arguments:
        articles: list of articles to be sorted. Defaults to _g.articleList
                  (but this makes a copy, so it doesn't get modified).
        refnos  : reference numbers corresponding to the articles. Defaults to
                  range(1, len(articles) + 1).
        mode    : mode to sort by. The allowed values are the keys of
                  _g.sortKey, which right now are "yja", "timeOpened", and
                  "timeAdded". Defaults to _g.sortMode.
        reverse : whether to sort in ascending order (True) or descending
                  (False). Defaults to _g.sortReverse.

    Returns:
        (articles, refnos): Sorted articles and refnos.
    """
    # Argument processing
    if articles is None:
        articles = _g.articleList
    if refnos is None:
        refnos = range(1, len(articles) + 1)
    if len(articles) != len(refnos):
        return _error("sortCopyArticles: articles and refnos "
                      "have different lengths ({} and {})".format(len(articles),
                                                                  len(refnos)))
    if mode is None:
        mode = _g.sortMode
    try:
        # Because we're sorting tuples, we need to apply _g.sortKey[mode] to
        # the first element of the tuple, hence the added complexity.
        key = (lambda t: _g.sortKey[mode](t[0]))
    except KeyError:
        return _error("sortCopyArticles: invalid mode '{}' provided".format(mode))
    if reverse is None:
        reverse = _g.sortReverse

    # Copy and sort the list
    arts = deepcopy(articles)
    refnos = deepcopy(refnos)  # this is probably overkill, but might as well
    arts, refnos = zip(*sorted(zip(arts, refnos), key=key, reverse=reverse))
    return (arts, refnos)


@_asynchelpdeco
@_timedeco
async def updateRef(args):
    """
    Usage: u[pdate] refno[...]

    Update one or more references using the Crossref API. If any differences in
    the metadata are detected, then the user is prompted to accept or reject
    the changes before applying them to the database.

    At least one refno must be specified. For more details about the format in
    which refnos are specified, type 'h list'.

    ** Function details **
    This is only meant to be invoked from the command-line.

    Arguments:
        args: List of command-line options.

    Returns:
        Return codes as defined in _ret.
    """
    if _g.articleList == []:
        return _error("updateRef: no articles have been loaded")
    if args == []:
        return _error("updateRef: no references selected")

    # no formats to process; just refnos
    refnos = refMgmt.parseRefno(",".join(args))
    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos):
        return _error("updateRef: invalid argument{} '{}' given".format(_p(args),
                                                                        " ".join(args)))

    # create spinner
    prog = _progress(len(refnos))
    spin = asyncio.create_task(_spinner("Fetching metadata", prog))

    # Lists containing dictionaries of old and new articles. Since data is
    # being pulled asynchronously, we need to be careful with the sorting. We
    # first sort refnos & aolds by the DOI.
    aolds = [_g.articleList[r - 1] for r in refnos]
    anews = []
    aolds, refnos = zip(*sorted(zip(aolds, refnos),
                                key=(lambda t: t[0]["doi"])))

    # Perform asynchronous HTTP requests
    dois = [aold["doi"] for aold in aolds]
    crefCoros = [refMgmt.DOIToMetadata(doi, _g.ahSession) for doi in dois]
    for coro in asyncio.as_completed(crefCoros):
        anews.append(await coro)
        prog.incr(1)
    # Kill spinner, and actually wait for it to be killed, otherwise
    # the output below gets messed up terribly
    spin.cancel()
    await asyncio.sleep(0)

    # After we finish pulling anews, it is out of order. We can sort anews by
    # the DOI to get the same ordering as aolds and refnos. Then we re-sort
    # everything by increasing refno so that we can present them to the user
    # in increasing order of refno. But we deal with that later.
    anews.sort(key=itemgetter("doi"))
    # Because tuples are sorted by the first component, and refno's components
    # are plain old ints, we don't need to specify a key.
    refnos, aolds, anews = zip(*sorted(zip(refnos, aolds, anews)))

    yes = 0
    for r, aold, anew in zip(refnos, aolds, anews):
        if anew["title"] is None:
            _error("updateRef: ref {} has an invalid DOI '{}'".format(r, aold["doi"]))
        # copy over timeAdded, timeOpened data from old reference
        anew["timeAdded"] = aold["timeAdded"]
        anew["timeOpened"] = aold["timeOpened"]
        # calculate and report differences
        ndiffs = refMgmt.diffArticles(aold, anew)
        if ndiffs == 0:
            print("updateRef: no new data for ref {} found on Crossref".format(r))
        else:
            # Must use a new PromptSession().prompt_async(), otherwise it gets messed up.
            msg = "updateRef: accept new data for ref {} (y/n)? ".format(r)
            style = pt.styles.Style.from_dict({"prompt": _g.ptBlue, "": _g.ptGreen})
            try:
                ans = await pt.PromptSession().prompt_async(msg, style=style)
            except (EOFError, KeyboardInterrupt):
                ans = "no"
            if ans.strip().lower() in ["", "y", "yes"]:
                _g.articleList[r - 1] = anew
                print("updateRef: successfully updated ref {}".format(r))
                yes += 1
            else:  # ok, it isn't really (y/n), it's (y/not y)
                print("updateRef: rejected changes for ref {}".format(r))
    print("updateRef: {} article{} updated".format(yes, _p(yes)))
    _g.changes += ["update"] * yes
    return _ret.SUCCESS


@_asynchelpdeco
@_timedeco
async def deleteRef(args):
    """
    Usage: d[elete] refno[...]

    Deletes one or more references, as well as the PDFs associated with them.

    ** Function details **
    This is only meant to be invoked from the command-line.

    Arguments:
        args: List of command-line options.

    Returns:
        Return codes as defined in _ret.
    """
    if _g.articleList == []:
        return _error("deleteRef: no articles have been loaded")
    if args == []:
        return _error("deleteRef: no references selected")

    # no formats to process; just refnos
    refnos = refMgmt.parseRefno(",".join(args))
    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos):
        return _error("deleteRef: invalid argument{} '{}' given".format(_p(args),
                                                                        " ".join(args)))

    # Must use a new PromptSession().prompt_async(), otherwise it gets messed up.
    yes = 0
    msg = "deleteRef: really delete ref{} {} (y/n)? ".format(_p(refnos),
                                                             ", ".join(str(r) for r in refnos))
    style = pt.styles.Style.from_dict({"prompt": _g.ptBlue, "": _g.ptGreen})
    try:
        ans = await pt.PromptSession().prompt_async(msg, style=style)
    except (EOFError, KeyboardInterrupt):
        ans = "no"
    if ans.strip().lower() in ["", "y", "yes"]:
        # Delete PDFs first.
        await deletePDF(args, silent=True)
        # Must sort the list in descending order so that you don't get earlier
        #  deletions affecting later ones!!
        refnos.sort(reverse=True)
        for r in refnos:
            del _g.articleList[r - 1]
            yes += 1
        print("deleteRef: {} ref{} deleted".format(yes, _p(yes)))
        _g.changes += ["delete"] * yes
    else:
        print("deleteRef: no refs deleted")
    return _ret.SUCCESS


@_asynchelpdeco
@_timedeco
async def importPDF(args=None):
    """
    Usage: i[mport] path[...]

    Import a PDF into the database. Automatically attempts to detect the DOI
    from the PDF and fetch the corresponding metadata. The paths provided can
    either be single PDF files, or folders containing multiple PDF files.
    (Note that directories are not searched recursively.)

    If this fails, add the DOI manually (with 'a <doi>'), then add the
    PDF with 'ap <refno>'.

    ** Function details **
    This is only meant to be invoked from the command-line.

    Arguments:
        args: List of command-line options.

    Returns:
        Tuple (yes, no) containing number of PDFs successfully added and
        number of PDFs that were not added.
    """
    # Argument processing
    if args == []:
        return _error("importPDF: no references selected")

    # Get paths from the args.
    paths = []
    for arg in args:
        p = Path(arg).resolve().expanduser()
        # If it's a file, add it directly
        if p.exists() and p.is_file():
            paths.append(p)
        # If it's a directory, add all the PDF files inside
        elif p.exists() and p.is_dir():
            paths += [f for f in p.iterdir() if f.suffix == ".pdf"]
        else:
            _error("importPDF: invalid path '{}' provided".format(arg))

    yes, no = 0, 0
    # Process every PDF file found.
    for path in paths:
        # Try to get the DOI
        doi = refMgmt.PDFToDOI(path)
        if doi == _ret.FAILURE:
            no += 1
        else:
            print("importPDF: detected DOI {} for PDF '{}'".format(doi, path))
            # Check whether it's already in the database
            for refno, a in enumerate(_g.articleList, start=1):
                if doi == a["doi"]:
                    _error("importPDF: DOI {} already in database. Use "
                           "'ap {}' to associate this PDF "
                           "with it.".format(doi, refno))
                    no += 1
                    break
            else:  # ok, I don't like for-else, but it just works here...
                # Prompt user whether they want to add it
                addyes, addno = await addRef([doi])
                yes += addyes
                no += addno
                if addyes == 1:
                    # Save the pdf into the database.
                    await refMgmt.savePDF(path, doi, "pdf")
    # Trigger autosave
    _g.changes += ["import"] * yes
    return yes, no


@_asynchelpdeco
@_timedeco
async def addPDF(args):
    """
    Usage: addpdf (or ap) refno[...]

    Add a PDF to an existing reference in the database. Arguments can be
    provided as refnos. See 'h list' for more details on the syntax. This
    function will then prompt you for a link to the file; this can be provided
    as either a URL or an (absolute) file system path. File paths can be most
    easily provided by dragging-and-dropping a file into the terminal window.

    Note that PDFs that have already been saved cannot be changed using this
    command. You have to delete the PDF first (using 'dp'), then re-add the
    new PDF.

    ** Function details **
    This is meant to be only invoked from the command-line.

    Arguments:
        args: List of command-line arguments.

    Returns: TBD.
    """
    if _g.articleList == []:
        return _error("addPDF: no articles have been loaded")
    if args == []:
        return _error("addPDF: no references selected")

    # no formats to process; just refnos
    refnos = refMgmt.parseRefno(",".join(args))
    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos):
        return _error("addPDF: invalid argument{} '{}' given".format(_p(args),
                                                                     " ".join(args)))

    formats = ["pdf", "si"]
    yes, no = 0, 0
    # We wrap the whole thing in try/except to catch Ctrl-C, which will get us
    # out of the entire loop quickly. Sending Ctrl-D just moves us to the next
    # refno.
    try:
        for i, r in enumerate(refnos):
            # Print the title.
            doi = _g.articleList[r - 1]["doi"]
            title = _g.articleList[r - 1]["title"]
            year = _g.articleList[r - 1]["year"]
            author = _g.articleList[r - 1]["authors"][0]["family"]
            if i != 0:
                print()  # Just a bit easier to read.
            print("{}({}) {} {}:{} {}".format(_g.ansiBold, r, author, year,
                                               _g.ansiReset, title))

            # Check whether the PDFs are already available.
            avail = {}  # mapping of format -> Bool
            for f in formats:
                p = _g.currentPath.parent / f / (doi.replace('/','#') + ".pdf")
                if p.exists() and p.is_file():
                    print(" {}\u2714{} {}   ".format(_g.ansiDiffGreen, _g.ansiReset, f))
                    avail[f] = True
                else:
                    print(" {}\u2718{} {}   ".format(_g.ansiDiffRed, _g.ansiReset, f))
                    avail[f] = False

            style = pt.styles.Style.from_dict({"prompt": _g.ptBlue, "": _g.ptGreen})
            msg = {"pdf": "addPDF: provide path to PDF (leave empty to skip): ",
                   "si": "addPDF: provide path to SI (leave empty to skip): "}
            # If both are available
            if avail["pdf"] and avail["si"]:
                print("Both PDF and SI found.")
                continue
            # At least one isn't available
            else:
                for f in (fmt for fmt in avail.keys() if not avail[fmt]):
                    try:
                        ans = await pt.PromptSession().prompt_async(msg[f],
                                                                    style=style)
                    except EOFError:  # move on to next question...
                        continue
                    if ans.strip():
                        saveTask = asyncio.create_task(refMgmt.savePDF(ans, doi, f))
                        await asyncio.wait([saveTask])
                        if saveTask.result() == _ret.FAILURE:
                            no += 1
                        else:
                            yes += 1
    except KeyboardInterrupt:
        pass

    print("addPDF: {} PDFs added, {} failed".format(yes, no))
    return _ret.SUCCESS


@_asynchelpdeco
@_timedeco
async def deletePDF(args, silent=False):
    """
    Usage: deletepdf (or dp) refno[...]

    Deletes PDF files associated with one or more references.

    At least one refno must be specified. For more details about how to specify
    refnos, type 'h list'.

    ** Function details **
    Deletes PDFs.

    Arguments:
        args  : List of command-line arguments.
        silent: If False, prompts the user for confirmation before deleting.

    Returns:
        Return values as described in _ret.
    """
    if _g.articleList == []:
        return _error("deletePDF: no articles have been loaded")
    if args == []:
        return _error("deletePDF: no references selected")

    # no formats to process; just refnos
    refnos = refMgmt.parseRefno(",".join(args))
    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos):
        return _error("deletePDF: invalid argument{} '{}' given".format(_p(args),
                                                                        " ".join(args)))

    yes = 0
    for i, r in enumerate(refnos):
        # Print the title.
        doi = _g.articleList[r - 1]["doi"]
        title = _g.articleList[r - 1]["title"]
        year = _g.articleList[r - 1]["year"]
        author = _g.articleList[r - 1]["authors"][0]["family"]
        if not silent:
            if i != 0:
                print()  # Just a bit easier to read.
            print("{}({}) {} {}:{} {}".format(_g.ansiBold, r, author, year,
                                               _g.ansiReset, title))
        # Check whether the PDFs are actually available.
        avail = {}  # mapping of format -> Bool
        for f in ["pdf", "si"]:
            p = _g.currentPath.parent / f / (doi.replace('/','#') + ".pdf")
            if p.exists() and p.is_file():
                avail[f] = True
                if not silent:
                    print(" {}\u2714{} {}   ".format(_g.ansiDiffGreen, _g.ansiReset, f))
            else:
                avail[f] = False
                if not silent:
                    print(" {}\u2718{} {}   ".format(_g.ansiDiffRed, _g.ansiReset, f))

        # If both are not available
        if not avail["pdf"] and not avail["si"]:
            print("No PDFs associated with reference {} found.".format(r))
            continue
        # At least one available. Prompt user for format to delete
        else:
            if not silent:
                style = pt.styles.Style.from_dict({"prompt": "{} bold".format(_g.ptBlue),
                                                   "": _g.ptGreen})
                msg = "deletePDF: Confirm deletion by typing formats to be deleted: "
                try:
                    ans = await pt.PromptSession().prompt_async(msg)
                except (KeyboardInterrupt, EOFError):
                    continue  # to the next refno
                # Parse user input and delete files as necessary
                else:
                    ans = ans.replace("pdf", "p").replace("si", "s")
                    fs = refMgmt.parseFormat(ans)
                    if fs == _ret.FAILURE or any(f not in ['p', 's'] for f in fs) \
                            or ('p' in fs and not avail["pdf"]) \
                            or ('s' in fs and not avail["si"]):
                        _error("deletePDF: invalid response, no PDFs deleted")
                        continue  # to the next refno
            else:
                # Didn't want to be prompted. Just delete everything without
                # any error checking.
                fs = ['p', 's']

            # If we reached here, that means we should delete files.
            if 'p' in fs:
                path = _g.currentPath.parent / "pdf" / \
                    (doi.replace('/','#') + ".pdf")
                try:
                    subprocess.run(["rm", str(path)],
                                   stderr=subprocess.DEVNULL,
                                   check=True)
                except subprocess.CalledProcessError:  # file not found
                    pass
                else:
                    yes += 1
            if 's' in fs:
                path = _g.currentPath.parent / "si" / \
                    (doi.replace('/','#') + ".pdf")
                try:
                    subprocess.run(["rm", str(path)],
                                   stderr=subprocess.DEVNULL,
                                   check=True)
                except subprocess.CalledProcessError:  # file not found
                    pass
                else:
                    yes += 1

    print("deletePDF: {} PDFs deleted".format(yes))
    return _ret.SUCCESS


@_asynchelpdeco
@_timedeco
async def fetchPDF(args):
    """
    Usage: f[etch] refno[...]

    Attempts to find the URL, and download, the full text PDF for the specified
    refnos. For more information on how to specify refnos, type 'h list'.

    The heuristics used are hardcoded, so are not guaranteed to work on every
    DOI, and indeed even those that work now may break later. But the major
    publishers all work (for now). Supported publishers are: ACS, Wiley,
    Elsevier, Nature, Science, Springer, Taylor and Francis, and Annual
    Reviews (as of 27 May 2020).

    Note that in order to download the full-text PDF, institutional access must
    be enabled, e.g. via VPN. (Or, of course, the PDF must be open-access.)
    """
    if _g.articleList == []:
        return _error("fetchPDF: no articles have been loaded")
    if args == []:
        return _error("fetchPDF: no references selected")

    # no formats to process; just refnos
    refnos = refMgmt.parseRefno(",".join(args))
    # Check the returned values
    ls = len(_g.articleList)
    if refnos is _ret.FAILURE or refnos == [] or any(r > ls for r in refnos):
        return _error("fetchPDF: invalid argument{} '{}' given".format(_p(args),
                                                                       " ".join(args)))

    # Check which ones need downloading
    dois = []
    for r in refnos:
        doi = _g.articleList[r - 1]["doi"]
        p = _g.currentPath.parent / "pdf" / (doi.replace('/','#') + ".pdf")
        if not (p.exists() and p.is_file()):
            dois.append(doi)
        else:
            print("fetchPDF: PDf for ref {} already in library".format(r))

    yes, no = 0, 0
    # Start the downloads!
    if len(dois) > 0:
        prog = _progress(len(dois))
        spin = asyncio.create_task(_spinner("Obtaining URLs", prog))
        results = []

        # Each coroutine returns a 2-tuple; the first component is
        # the doi, and the second is the URL if it didn't fail (or
        # a _ret.FAILURE if it did).
        coros = [refMgmt.DOIToFullPDFURL(doi, _g.ahSession) for doi in dois]
        for coro in asyncio.as_completed(coros):
            results.append(await coro)
            prog.incr()
        spin.cancel()
        await asyncio.sleep(0)

        for result in results:
            if result[1] == _ret.FAILURE:
                no += 1
            else:
                x = await refMgmt.savePDF(result[1], result[0], "pdf")
                if x == _ret.FAILURE:
                    no += 1
                else:
                    yes += 1

    print("fetchPDF: {} PDFs successfully fetched, {} failed".format(yes, no))
    return _ret.SUCCESS

