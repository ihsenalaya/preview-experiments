"""Publication-ready matplotlib helpers (Times New Roman, 600 dpi, colorblind-safe palette)."""
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.dpi": 150,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.5,
})

# Colorblind-safe palette (Wong 2011)
PALETTE = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "sky": "#56B4E9",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "yellow": "#F0E442",
    "black": "#000000",
}

ISO_ON_COLOR = PALETTE["blue"]
ISO_OFF_COLOR = PALETTE["vermillion"]


def figure(width_in: float = 3.5, height_in: float = 2.6):
    """Single-column figure (3.5 in = half a letter page with margins)."""
    return plt.subplots(figsize=(width_in, height_in))


def two_col_figure(height_in: float = 2.6):
    """Double-column figure (7.0 in)."""
    return plt.subplots(figsize=(7.0, height_in))


def box_compare(ax, data_on: list, data_off: list, labels=("Isolation ON", "Isolation OFF"),
                ylabel: str = "", title: str = "") -> None:
    bp = ax.boxplot(
        [data_on, data_off],
        labels=labels,
        patch_artist=True,
        medianprops={"color": "black", "linewidth": 1.5},
        widths=0.5,
    )
    bp["boxes"][0].set_facecolor(ISO_ON_COLOR + "88")
    bp["boxes"][1].set_facecolor(ISO_OFF_COLOR + "88")
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)


def bar_compare(ax, categories: list, values_on: list, values_off: list,
                ylabel: str = "", title: str = "") -> None:
    x = np.arange(len(categories))
    w = 0.35
    ax.bar(x - w / 2, values_on, w, label="Isolation ON", color=ISO_ON_COLOR + "cc")
    ax.bar(x + w / 2, values_off, w, label="Isolation OFF", color=ISO_OFF_COLOR + "cc")
    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    ax.legend()


def annotate_p(ax, x1: float, x2: float, y: float, p: float, dy: float = 0.02) -> None:
    """Draw a significance bracket between x1 and x2."""
    label = f"p={p:.3f}" if p >= 0.001 else "p<0.001"
    if p < 0.05:
        label += " *"
    ax.plot([x1, x1, x2, x2], [y, y + dy, y + dy, y], lw=0.8, color="black")
    ax.text((x1 + x2) / 2, y + dy * 1.1, label, ha="center", va="bottom", fontsize=8)


def save(fig, path: str) -> None:
    fig.savefig(path)
    print(f"Figure saved: {path}")
