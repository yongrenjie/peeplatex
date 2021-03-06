# cygnet

An extremely minimalistic reference manager written in Python 3.

Install:

    pip install cygnet

Package dependencies:
 - `aiohttp`
 - `prompt_toolkit`
 - `pyyaml`
 - `unidecode`

## Function for autoexpanding DOIs in Vim

After installing `cygnet` citations can be generated (in Python) using

```python
import cygnet
cygnet.cite(doi, type="bib")
```

where `doi` is the DOI of the article given as a string. (Try it in a REPL!)

A short Vimscript function (and key mapping) that leverages this functionality is as follows.
There is some code to ensure that each article is always surrounded by one line of whitespace (a largely cosmetic option).

```vim
function ExpandDOI()
let doi = expand("<cWORD>")
echo "expanding DOI " .. doi .. "..."
python3<<EOF
import vim
from cygnet import cite
# get the citation
doi = vim.eval('expand("<cWORD>")')
try:
    citation = cite(doi, type="bib")
    citation = citation.replace("'", "''")
except Exception as e:
    citation = "error"
vim.command("let citation='{}'".format(citation))
EOF
if citation != "error"
    let lineno = line(".")
    " twiddle with empty lines before citation
    if !empty(trim(getline(line(".") - 1)))
        let x = append(line(".") - 1, "")
        let lineno += 1
    endif
    " replace the line with the citation
    put =citation | redraw
    " twiddle with empty lines after citation
    if !empty(trim(getline(line(".") + 1)))
        let x = append(line("."), "")
    endif
    execute lineno .. " delete _"
else
    redraw | echohl ErrorMsg | echo "invalid DOI " .. doi | echohl None
endif
endfunction

nnoremap <leader>e :call ExpandDOI() <CR>
```

This can be placed inside, for example, `~/.vim/ftplugin/bib.vim`.
After that, pressing `<leader>e` when the cursor is over a DOI should automatically expand it into a full Bib(La)TeX reference.
Note that the line containing the DOI will be deleted, so it should be placed on a line of its own!
