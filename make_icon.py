"""Gera icon.ico para o AutoClicker: cursor de mouse com anéis de clique."""

from PIL import Image, ImageDraw

SIZE = 256


def make_base_image():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo: quadrado arredondado com gradiente azul -> roxo
    bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    top_color = (37, 99, 235)    # azul
    bottom_color = (109, 40, 217)  # roxo
    for y in range(SIZE):
        t = y / SIZE
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        bg_draw.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))

    mask = Image.new("L", (SIZE, SIZE), 0)
    mask_draw = ImageDraw.Draw(mask)
    radius = 56
    mask_draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)
    img.paste(bg, (0, 0), mask)
    draw = ImageDraw.Draw(img)

    # Anéis de clique (indicam "auto clique") atrás do cursor
    ring_center = (168, 92)
    for radius, width, alpha in [(46, 7, 130), (66, 6, 90), (86, 5, 55)]:
        bbox = [
            ring_center[0] - radius, ring_center[1] - radius,
            ring_center[0] + radius, ring_center[1] + radius,
        ]
        draw.arc(bbox, start=300, end=140, fill=(255, 255, 255, alpha), width=width)

    # Cursor de mouse (seta clássica), branco com contorno sutil
    cursor = [
        (70, 56), (70, 190), (104, 158), (126, 202),
        (146, 192), (124, 150), (172, 150),
    ]
    draw.polygon(cursor, fill=(255, 255, 255, 255), outline=(20, 20, 40, 255))

    # Ponto de clique em destaque
    draw.ellipse([150, 78, 172, 100], fill=(250, 204, 21, 255))

    return img


def main():
    img = make_base_image()
    sizes = [256, 128, 64, 48, 32, 16]
    img.save(
        "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    img.save("icon_preview.png")
    print("icon.ico gerado")


if __name__ == "__main__":
    main()
