def calculate_resolution(target_ratio, source_size, base_dim):
    # Determine ratio
    if target_ratio:
        ratio = target_ratio
    else:
        if source_size and source_size[1] > 0:
            ratio = source_size[0] / source_size[1]
        else:
            ratio = 16/9
            
    # Calculate w, h
    if ratio >= 1:
        # Horizontal: base_dim is height
        h = base_dim
        w = int(h * ratio)
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        return w, h
    else:
        # Vertical: base_dim is width
        w = base_dim
        h = int(w / ratio)
        if w % 2 != 0: w += 1
        if h % 2 != 0: h += 1
        return w, h

def test():
    test_cases = [
        {"name": "16:9 Horizontal", "ratio": 16/9, "source": None, "base": 1080, "expect": (1920, 1080)},
        {"name": "9:16 Vertical", "ratio": 9/16, "source": None, "base": 1080, "expect": (1080, 1920)},
        {"name": "4:3 Horizontal", "ratio": 4/3, "source": None, "base": 1080, "expect": (1440, 1080)},
        {"name": "3:4 Vertical", "ratio": 3/4, "source": None, "base": 1080, "expect": (1080, 1440)},
        {"name": "Source 1:1", "ratio": None, "source": (500, 500), "base": 1080, "expect": (1080, 1080)},
        {"name": "Source 16:9", "ratio": None, "source": (1920, 1080), "base": 1080, "expect": (1920, 1080)},
        {"name": "Source 9:16", "ratio": None, "source": (1080, 1920), "base": 1080, "expect": (1080, 1920)},
    ]
    
    for case in test_cases:
        w, h = calculate_resolution(case["ratio"], case["source"], case["base"])
        print(f"Case {case['name']}: {w}x{h} (Expected: {case['expect'][0]}x{case['expect'][1]}) -> {'PASS' if (w, h) == case['expect'] else 'FAIL'}")

if __name__ == "__main__":
    test()