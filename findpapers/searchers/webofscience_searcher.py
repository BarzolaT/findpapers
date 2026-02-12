
from typing import Optional
from findpapers.models.search import Search


BASE_URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"


def _get_search_url(search: Search, start_record: Optional[int] = 0) -> str:
    """
    This method return the URL to be used to retrieve data from webofscience database
    See https://developer.clarivate.com/apis/wos for query tips

    Parameters
    ----------
    search : Search
        A search instance
    start_record : str
        Sequence number of first record to fetch, by default 0

    Returns
    -------
    str
        a URL to be used to retrieve data from arXiv database
    """
    query = search.query.replace(" AND NOT ", " NOT ")
    raise NotImplementedError
