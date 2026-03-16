from textual.theme import Theme

amber_terminal = Theme(
    name="amber-terminal",
    dark=True,
    background="#140800",
    surface="#1F0D00",
    panel="#2A1300",
    foreground="#FFB000",
    primary="#CC8800",
    secondary="#7A4F00",
    accent="#FFCC33",
    warning="#FF8800",
    error="#FF3300",
    success="#88DD00",
    luminosity_spread=0.1,
    text_alpha=0.95,
    variables={
        "scrollbar-background": "#1F0D00",
        "scrollbar-background-hover": "#1F0D00",
        "scrollbar-background-active": "#1F0D00",
        "scrollbar-corner-color": "#1F0D00",
    },
)

green_terminal = Theme(
    name="green-terminal",
    dark=True,
    background="#001200",
    surface="#001A00",
    panel="#002300",
    foreground="#33FF33",
    primary="#00CC00",
    secondary="#006600",
    accent="#66FF66",
    warning="#CCFF00",
    error="#FF3300",
    success="#00FFAA",
    luminosity_spread=0.1,
    text_alpha=0.95,
    variables={
        "scrollbar-background": "#001A00",
        "scrollbar-background-hover": "#001A00",
        "scrollbar-background-active": "#001A00",
        "scrollbar-corner-color": "#001A00",
    },
)

CUSTOM_THEMES = [amber_terminal, green_terminal]
