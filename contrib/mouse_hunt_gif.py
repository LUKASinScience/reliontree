"""Mouse hunts cheese across a RELION job tree -> animated GIF.

The anecdote: in relion, the mouse hunts down exactly one piece of cheese
per job, all the way to the end. reliontree is about the whole job tree --
here the mouse runs the full hunting journey across every job in one DFS
pass, eating a piece of cheese at each job node along the way.

No argument: built-in demo tree.
With an argument (path to a RELION project directory): the real job tree
from reliontree.relion_pipeline.load_pipeline() + build_parents().
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---- Demo-Jobtree: {job: [child_jobs]} -----------------------------------
DEMO_TREE = {
    "Import": ["MotionCorr"],
    "MotionCorr": ["CtfFind"],
    "CtfFind": ["AutoPick"],
    "AutoPick": ["Extract"],
    "Extract": ["Class3D"],
    "Class3D": ["Refine3D"],
    "Refine3D": [],
}


def load_real_tree(project_dir):
    """Build {job: [child_jobs]} from a real RELION project."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from reliontree.relion_pipeline import load_pipeline, build_parents

    procs, node_to_prod, proc_to_in = load_pipeline(Path(project_dir))
    parents = build_parents(procs, node_to_prod, proc_to_in)

    tree = {p: [] for p in procs}
    roots = []
    for proc, pars in parents.items():
        if pars:
            for par in pars:
                tree[par].append(proc)
        else:
            roots.append(proc)
    if not roots:
        raise ValueError("no root job found (empty or cyclic project)")
    # Synthetic root if several start jobs run in parallel.
    if len(roots) > 1:
        tree["__start__"] = roots
        root = "__start__"
    else:
        root = roots[0]
    return tree, root

W, H = 720, 360
MOUSE = '"""(_,_">'
CHEESE = "(o)"
BG = (12, 12, 12)
FG = (230, 230, 230)
DIM = (90, 90, 90)

FONT = ImageFont.load_default()
LINE_H = 22
PROMPT = "$ "


def dfs_order(tree, root):
    """Preorder DFS job sequence -- the mouse's hunting route."""
    order = [root]

    def visit(node):
        for c in tree[node]:
            order.append(c)
            visit(c)

    visit(root)
    return order


def draw_frame(job_lines, mouse_line, mouse_x, cheese_x, eaten):
    """One black terminal frame: job names as scrolled-in lines, the mouse
    running along the current line hunting that job's one piece of cheese
    -- the cheese always flees a step ahead until caught at the line end."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    for i, job in enumerate(job_lines):
        y = 10 + i * LINE_H
        color = DIM if i < mouse_line else FG
        d.text((10, y), f"{PROMPT}{job}", fill=color, font=FONT)

    y = 10 + mouse_line * LINE_H
    if not eaten:
        d.text((cheese_x, y), CHEESE, fill=(200, 160, 40), font=FONT)
    d.text((mouse_x, y), MOUSE, fill=FG, font=FONT)

    return img


def main(out="relion_tree_hunt.gif", project_dir=None, steps_per_line=90):
    tree, root = (load_real_tree(project_dir) if project_dir else (DEMO_TREE, "Import"))
    jobs = dfs_order(tree, root)

    frames = []
    shown = []
    mouse_w = int(FONT.getlength(MOUSE))
    cheese_gap = 60
    run_w = W - 10 - mouse_w - cheese_gap
    for line, job in enumerate(jobs):
        shown.append(job)
        for step in range(steps_per_line):
            x = 10 + int(run_w * step / (steps_per_line - 1))
            last = step == steps_per_line - 1
            frames.append(draw_frame(shown, line, x, x + cheese_gap, eaten=last))

    frames.append(draw_frame(shown, len(jobs) - 1, 10, 10, eaten=True))

    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=45,
        loop=0,
    )
    print(f"wrote: {out} ({len(frames)} frames)")


if __name__ == "__main__":
    main(project_dir=sys.argv[1] if len(sys.argv) > 1 else None)
