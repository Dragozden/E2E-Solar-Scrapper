from bs4 import BeautifulSoup

def parse_html(html: str):
    soup = BeautifulSoup(html, "lxml")

    return soup