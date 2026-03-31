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
    warning="#CC8800",
    error="#FF3300",
    success="#FFB000",
    luminosity_spread=0.1,
    text_alpha=0.95,
    variables={
        "scrollbar-background": "#1F0D00",
        "scrollbar-background-hover": "#1F0D00",
        "scrollbar-background-active": "#1F0D00",
        "scrollbar-corner-color": "#1F0D00",
        "text-muted": "#CC8800",
        "text-disabled": "#7A4F00",
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
    warning="#00CC00",
    error="#FF3300",
    success="#33FF33",
    luminosity_spread=0.1,
    text_alpha=0.95,
    variables={
        "scrollbar-background": "#001A00",
        "scrollbar-background-hover": "#001A00",
        "scrollbar-background-active": "#001A00",
        "scrollbar-corner-color": "#001A00",
        "text-muted": "#00CC00",
        "text-disabled": "#006600",
        "block-cursor-foreground": "#001200",
        "block-cursor-blurred-foreground": "#33FF33",
    },
)

CUSTOM_THEMES = [amber_terminal, green_terminal]
