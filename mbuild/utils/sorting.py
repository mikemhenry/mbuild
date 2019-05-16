import re


def _atoi(text):
    return int(text) if text.isdigit() else text


def natural_sort(text):
    return [_atoi(a) for a in re.split(r"(\d+)", text)]


def _natural_sort(text):
    return [_atoi(a) for a in re.split(r"(\d+)", text[0])]
