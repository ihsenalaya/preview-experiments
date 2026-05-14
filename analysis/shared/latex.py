"""Generate publication-ready LaTeX tables (booktabs style)."""


def table(headers: list[str], rows: list[list], caption: str = "", label: str = "") -> str:
    col_fmt = "l" + "r" * (len(headers) - 1)
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\small",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        rf"\begin{{tabular}}{{{col_fmt}}}",
        r"\toprule",
        " & ".join(f"\\textbf{{{h}}}" for h in headers) + r" \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(str(c) for c in row) + r" \\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(lines)


def fmt_p(p: float) -> str:
    if p < 0.001:
        return r"$<$0.001"
    return f"{p:.3f}"


def fmt_a12(a12: float) -> str:
    return f"{a12:.2f} ({_a12_label(a12)})"


def _a12_label(a12: float) -> str:
    if a12 >= 0.71 or a12 <= 0.29:
        return "large"
    if a12 >= 0.64 or a12 <= 0.36:
        return "medium"
    if a12 >= 0.56 or a12 <= 0.44:
        return "small"
    return "negligible"
