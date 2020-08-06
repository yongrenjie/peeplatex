"""
listprint.py
------------

All functions needed to print lists. It's surprisingly complicated!
"""


import os
from copy import deepcopy
from itertools import zip_longest

from ._shared import *

_formatstr = "{0:<{1}}{2:{3}}{4:<{5}}{6:{7}}{8:{9}}"


def print_list(articles, refnos, max_auth=5):
    """
    Prints a series of articles and refnos, along with the PDF/SI availability
    of each article.

    Arguments:
        articles (list) : List of articles to be printed.
        refnos (list)   : List of refnos to be printed.

    The two lists must always be in the same order, i.e. article number 1
    corresponds to refno number 1, etc.

    Returns:
        None.

    Raises:
        ValueError if the two lists have different lengths.
    """
    if len(articles) != len(refnos):
        raise ValueError("articles and refnos do not have same length")

    # Make a copy of the articles
    articles = deepcopy(articles)

    # Calculate field sizes and set format string
    field_sizes = get_field_sizes(articles, refnos)

    # Construct and print the list header
    print_list_head(field_sizes)

    # Print all articles
    for article, refno in zip(articles, refnos):
        print_list_article(article, refno, field_sizes, max_auth=max_auth)


def print_list_head(field_sizes):
    """
    Prints the header of the list.
    """
    # blank row
    print()
    # header row
    print(_g.ansiBold
          + _formatstr.format("#", field_sizes["number"],
                              "Authors", field_sizes["author"],
                              "Year", field_sizes["year"],
                              "Journal", field_sizes["journal"],
                              "Title & DOI", field_sizes["title"])
          + _g.ansiReset)
    # a horizontal line
    print("-" * sum(field_sizes.values()))


def print_list_article(article, refno, field_sizes, max_auth):
    """
    Print one article.

    Arguments:
        article (dict)     : The article.
        refno (int)        : The reference number.
        field_sizes (dict) : The field sizes for each column of the list. These
                             are generated by get_field_sizes().
        max_auth (int)     : Number of authors to print. If 0 or negative
                             prints all authors.

    Returns: None.
    """
    # We now need to construct each column of information, one at a time.
    # 1. Number column (refno): just has one piece of information.
    number_column = [refno]
    # 2. Author column: Has all authors listed in the format 'JRJ Yong'
    # The field width has been calculated carefully earlier to make sure that
    # no names are clipped.
    author_column = article.format_authors(style="display")
    # Truncate author lists depending on max_auth
    if max_auth > 0 and len(author_column) > max_auth:
        author_column = [*author_column[:max_auth - 2],
                         "...",
                         author_column[-1]]
    # 3. Year column: just one piece of information
    year_column = [article.year]
    # 4. Journal column: has the journal short name, as well as volume info
    journal_column = [article.format_short_journalname(),
                      article.get_volume_info()]
    # 5. Title and DOI column: has title, DOI, and the availability
    # The title must be split according to the field width.
    n = field_sizes["title"]
    title_column = [article.title[i:i+n]
                    for i in range(0, len(article.title), n)]
    # Then we tack on the DOI and the availability string.
    title_column.extend([article.doi,
                         article.get_availability_string()])

    # Now, print everything!
    for number, author, year, journal, title in zip_longest(number_column,
                                                            author_column,
                                                            year_column,
                                                            journal_column,
                                                            title_column,
                                                            fillvalue=""):
        print(_formatstr.format(number, field_sizes["number"],
                                author, field_sizes["author"],
                                year, field_sizes["year"],
                                journal, field_sizes["journal"],
                                title, field_sizes["title"])
              )
    # Print blank line for readability
    print()


def get_field_sizes(articles, refnos, padding=2):
    """
    Calculates appropriate field sizes for list printing, i.e. the number of
    characters that each column should occupy.

    Arguments:
        articles (list of dict) : The articles to be printed.
        refnos (list of int)    : The reference numbers of the articles.
        padding (int)           : The padding between each column.

    Returns:
        Dictionary of field sizes, with keys "number", "author", "year",
        "journal", and "title" for each of the five respective columns.
    """
    number_fs = max(len(str(r)) for r in refnos) + padding
    author_fs = max(max(max(len(i)
                            for i in article.format_authors(style="display"))
                        for article in articles),
                    len("Authors")
                    ) + padding
    year_fs = 4 + padding
    journal_fs = max(max(len(art.format_short_journalname())
                         for art in articles),
                     max(len(art.get_volume_info()) for art in articles),
                     len("Journal")
                     ) + padding
    # Use up the remaining space in the terminal, but don't extend beyond the
    # longest title, as there's no need to.
    remaining_columns = (os.get_terminal_size().columns - number_fs - author_fs
                         - year_fs - journal_fs)
    title_fs = min(remaining_columns, max(len(a.title) for a in articles))
    # When you print ANSI escape codes, you have to make sure that all the
    # characters in the escape code are on the same line, otherwise the colour
    # for the subsequent lines gets completely messed up.
    # Strictly, only 37 characters are needed to ensure that this doesn't
    # happen, but 40 is a nice round number near there.
    title_fs = max(40, title_fs)

    return {"number": number_fs,
            "author": author_fs,
            "year": year_fs,
            "journal": journal_fs,
            "title": title_fs}
