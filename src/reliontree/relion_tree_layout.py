def layout_positions(layers, card_sizes, col_gap=16, row_gap=20):
    """Assign a 2D (x, y) top-left position to each job in `layers` (the
    chronological generation list returned by relion_pipeline.layers()).

    Content-aware and left-aligned rather than a fixed grid: each generation
    is a row starting at x=0 and growing rightward only as far as it
    actually has siblings (so a simple chain stays as a straight left-hand
    "trunk", and only real branch points indent right); row height is the
    tallest card in that generation, so rows only take as much vertical
    space as their content actually needs.

    `card_sizes`: {job_id: (width, height)} — the on-screen size each job's
    card will be drawn at. Jobs are vertically centered within their row if
    a sibling in the same generation is taller.

    Pure — no Qt/ChimeraX dependency, safe to unit test directly.
    """
    positions = {}
    y_cursor = 0
    for layer in layers:
        row_h = max((card_sizes.get(j, (0, 0))[1] for j in layer), default=0)
        x_cursor = 0
        for job in layer:
            w, h = card_sizes.get(job, (0, 0))
            positions[job] = (x_cursor, y_cursor + (row_h - h) / 2)
            x_cursor += w + col_gap
        y_cursor += row_h + row_gap
    return positions
