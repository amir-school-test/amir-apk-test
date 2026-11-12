"""
AMIR SYSTEM
QR Code Service (توليد رموز QR داخل التطبيق)

يولّد رمز QR بدون أي مكتبة خارجية (بايثون فقط)، حتى لا نضيف
متطلبات بناء جديدة على APK.

يدعم:
    - وضع Byte (أي نص).
    - مستوى تصحيح الأخطاء L أو M.
    - النسخ من 1 إلى 10 (حتى 213 بايت عند المستوى M).

الاستخدام:
    matrix = make_matrix("ADMIN:EXAM:abc")
    # matrix[row][col] == True تعني مربعًا أسود.

make_widget(matrix) يرجع عنصر Kivy يرسم الرمز (يعمل داخل التطبيق فقط).
"""

# ============================================================
# TABLES (النسخ 1..10)
# ============================================================

ECC_CODEWORDS_PER_BLOCK = {
    "L": (None, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18),
    "M": (None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26),
}

NUM_ERROR_CORRECTION_BLOCKS = {
    "L": (None, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4),
    "M": (None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5),
}

FORMAT_BITS = {"L": 1, "M": 0}

MIN_VERSION = 1
MAX_VERSION = 10


# ============================================================
# GF(256) / REED-SOLOMON
# ============================================================

def _gf_multiply(x, y):

    z = 0

    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x

    return z


def _rs_divisor(degree):

    result = [0] * (degree - 1) + [1]
    root = 1

    for _ in range(degree):

        for j in range(degree):

            result[j] = _gf_multiply(result[j], root)

            if j + 1 < degree:
                result[j] ^= result[j + 1]

        root = _gf_multiply(root, 0x02)

    return result


def _rs_remainder(data, divisor):

    result = [0] * len(divisor)

    for byte in data:

        factor = byte ^ result.pop(0)
        result.append(0)

        for i, coefficient in enumerate(divisor):
            result[i] ^= _gf_multiply(coefficient, factor)

    return result


# ============================================================
# CAPACITY
# ============================================================

def _num_raw_data_modules(version):

    result = (16 * version + 128) * version + 64

    if version >= 2:

        num_align = version // 7 + 2

        result -= (25 * num_align - 10) * num_align - 55

        if version >= 7:
            result -= 36

    return result


def _num_data_codewords(version, ecc):

    return (
        _num_raw_data_modules(version) // 8
        - ECC_CODEWORDS_PER_BLOCK[ecc][version]
        * NUM_ERROR_CORRECTION_BLOCKS[ecc][version]
    )


def _choose_version(byte_count, ecc):

    for version in range(MIN_VERSION, MAX_VERSION + 1):

        count_bits = 8 if version <= 9 else 16

        needed_bits = 4 + count_bits + byte_count * 8

        if needed_bits <= _num_data_codewords(version, ecc) * 8:
            return version

    raise ValueError(
        "The text is too long for the QR code generator."
    )


# ============================================================
# DATA ENCODING
# ============================================================

def _encode_data(data_bytes, version, ecc):

    bits = []

    def append(value, length):
        for i in reversed(range(length)):
            bits.append((value >> i) & 1)

    append(0x4, 4)                                  # Byte mode
    append(len(data_bytes), 8 if version <= 9 else 16)

    for byte in data_bytes:
        append(byte, 8)

    capacity_bits = _num_data_codewords(version, ecc) * 8

    append(0, min(4, capacity_bits - len(bits)))    # terminator
    append(0, -len(bits) % 8)                       # byte align

    pad = 0xEC

    while len(bits) < capacity_bits:
        append(pad, 8)
        pad ^= 0xEC ^ 0x11

    codewords = [0] * (len(bits) // 8)

    for i, bit in enumerate(bits):
        codewords[i >> 3] |= bit << (7 - (i & 7))

    return codewords


def _add_error_correction(data, version, ecc):

    num_blocks = NUM_ERROR_CORRECTION_BLOCKS[ecc][version]
    block_ecc_len = ECC_CODEWORDS_PER_BLOCK[ecc][version]

    raw_codewords = _num_raw_data_modules(version) // 8

    num_short_blocks = num_blocks - raw_codewords % num_blocks
    short_block_len = raw_codewords // num_blocks

    blocks = []
    divisor = _rs_divisor(block_ecc_len)

    k = 0

    for i in range(num_blocks):

        length = (
            short_block_len
            - block_ecc_len
            + (0 if i < num_short_blocks else 1)
        )

        block = data[k:k + length]
        k += length

        ecc_bytes = _rs_remainder(block, divisor)

        if i < num_short_blocks:
            block.append(0)

        blocks.append(block + ecc_bytes)

    result = []

    for i in range(len(blocks[0])):

        for j, block in enumerate(blocks):

            if (
                i != short_block_len - block_ecc_len
                or j >= num_short_blocks
            ):
                result.append(block[i])

    return result


# ============================================================
# MATRIX
# ============================================================

class _Builder:

    def __init__(self, version, ecc, codewords):

        self.version = version
        self.ecc = ecc
        self.size = version * 4 + 17

        self.modules = [
            [False] * self.size for _ in range(self.size)
        ]

        self.is_function = [
            [False] * self.size for _ in range(self.size)
        ]

        self._draw_function_patterns()
        self._draw_codewords(codewords)

    def _set_function(self, x, y, dark):

        self.modules[y][x] = bool(dark)
        self.is_function[y][x] = True

    def _alignment_positions(self):

        version = self.version

        if version == 1:
            return []

        num_align = version // 7 + 2

        step = (
            26 if version == 32
            else (version * 4 + num_align * 2 + 1)
            // (num_align * 2 - 2) * 2
        )

        result = [
            self.size - 7 - i * step
            for i in range(num_align - 1)
        ] + [6]

        return list(reversed(result))

    def _draw_finder(self, cx, cy):

        for dy in range(-4, 5):
            for dx in range(-4, 5):

                distance = max(abs(dx), abs(dy))

                x = cx + dx
                y = cy + dy

                if 0 <= x < self.size and 0 <= y < self.size:
                    self._set_function(x, y, distance not in (2, 4))

    def _draw_alignment(self, cx, cy):

        for dy in range(-2, 3):
            for dx in range(-2, 3):

                self._set_function(
                    cx + dx,
                    cy + dy,
                    max(abs(dx), abs(dy)) != 1
                )

    def _draw_function_patterns(self):

        size = self.size

        for i in range(size):
            self._set_function(6, i, i % 2 == 0)
            self._set_function(i, 6, i % 2 == 0)

        self._draw_finder(3, 3)
        self._draw_finder(size - 4, 3)
        self._draw_finder(3, size - 4)

        positions = self._alignment_positions()
        count = len(positions)

        for i in range(count):
            for j in range(count):

                if (
                    (i == 0 and j == 0)
                    or (i == 0 and j == count - 1)
                    or (i == count - 1 and j == 0)
                ):
                    continue

                self._draw_alignment(positions[i], positions[j])

        self._draw_format_bits(0)
        self._draw_version()

    def _draw_format_bits(self, mask):

        data = (FORMAT_BITS[self.ecc] << 3) | mask

        rem = data

        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)

        bits = ((data << 10) | rem) ^ 0x5412

        def bit(i):
            return (bits >> i) & 1

        size = self.size

        for i in range(0, 6):
            self._set_function(8, i, bit(i))

        self._set_function(8, 7, bit(6))
        self._set_function(8, 8, bit(7))
        self._set_function(7, 8, bit(8))

        for i in range(9, 15):
            self._set_function(14 - i, 8, bit(i))

        for i in range(0, 8):
            self._set_function(size - 1 - i, 8, bit(i))

        for i in range(8, 15):
            self._set_function(8, size - 15 + i, bit(i))

        self._set_function(8, size - 8, True)

    def _draw_version(self):

        if self.version < 7:
            return

        rem = self.version

        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)

        bits = (self.version << 12) | rem

        for i in range(18):

            bit = (bits >> i) & 1

            a = self.size - 11 + i % 3
            b = i // 3

            self._set_function(a, b, bit)
            self._set_function(b, a, bit)

    def _draw_codewords(self, data):

        size = self.size
        i = 0

        for right in range(size - 1, 0, -2):

            if right <= 6:
                right -= 1

            for vert in range(size):

                for j in range(2):

                    x = right - j

                    upward = ((right + 1) & 2) == 0

                    y = size - 1 - vert if upward else vert

                    if (
                        not self.is_function[y][x]
                        and i < len(data) * 8
                    ):

                        self.modules[y][x] = bool(
                            (data[i >> 3] >> (7 - (i & 7))) & 1
                        )

                        i += 1

    def apply_mask(self, mask):

        for y in range(self.size):
            for x in range(self.size):

                if mask == 0:
                    invert = (x + y) % 2 == 0
                elif mask == 1:
                    invert = y % 2 == 0
                elif mask == 2:
                    invert = x % 3 == 0
                elif mask == 3:
                    invert = (x + y) % 3 == 0
                elif mask == 4:
                    invert = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    invert = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    invert = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    invert = ((x + y) % 2 + x * y % 3) % 2 == 0

                if invert and not self.is_function[y][x]:
                    self.modules[y][x] = not self.modules[y][x]

    def penalty(self):

        size = self.size
        modules = self.modules

        score = 0

        lines = [row[:] for row in modules]
        lines += [
            [modules[y][x] for y in range(size)]
            for x in range(size)
        ]

        finder_a = [True, False, True, True, True, False, True]

        for line in lines:

            # القاعدة 1: تتابع من نفس اللون.
            run = 1

            for i in range(1, size):

                if line[i] == line[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run = 1

            if run >= 5:
                score += 3 + (run - 5)

            # القاعدة 3: نمط يشبه الـ finder.
            for i in range(size - 6):

                if line[i:i + 7] == finder_a:

                    before = line[max(0, i - 4):i]
                    after = line[i + 7:i + 11]

                    if (
                        len(before) == 4 and not any(before)
                    ) or (
                        len(after) == 4 and not any(after)
                    ):
                        score += 40

        # القاعدة 2: كتل 2x2 بنفس اللون.
        for y in range(size - 1):
            for x in range(size - 1):

                color = modules[y][x]

                if (
                    color == modules[y][x + 1]
                    and color == modules[y + 1][x]
                    and color == modules[y + 1][x + 1]
                ):
                    score += 3

        # القاعدة 4: توازن الأسود والأبيض.
        dark = sum(row.count(True) for row in modules)
        total = size * size

        k = -(-abs(dark * 20 - total * 10) // total) - 1

        score += max(0, k) * 10

        return score


# ============================================================
# PUBLIC API
# ============================================================

def make_matrix(text, ecc="M"):
    """
    يرجع مصفوفة (قائمة صفوف) من True/False لرمز QR يحمل النص.

    ValueError إذا كان النص طويلًا جدًا أو فارغًا.
    """

    if ecc not in ECC_CODEWORDS_PER_BLOCK:
        raise ValueError("ecc must be 'L' or 'M'.")

    data_bytes = str(text).encode("utf-8")

    if not data_bytes:
        raise ValueError("The text is empty.")

    version = _choose_version(len(data_bytes), ecc)

    codewords = _encode_data(data_bytes, version, ecc)
    all_codewords = _add_error_correction(codewords, version, ecc)

    builder = _Builder(version, ecc, all_codewords)

    best_mask = 0
    best_penalty = None

    for mask in range(8):

        builder.apply_mask(mask)
        builder._draw_format_bits(mask)

        penalty = builder.penalty()

        if best_penalty is None or penalty < best_penalty:
            best_mask = mask
            best_penalty = penalty

        builder.apply_mask(mask)

    builder.apply_mask(best_mask)
    builder._draw_format_bits(best_mask)

    return [row[:] for row in builder.modules]


# ============================================================
# KIVY WIDGET (داخل التطبيق فقط)
# ============================================================

def make_widget(matrix, **kwargs):
    """
    عنصر Kivy يرسم المصفوفة بمربعات سوداء على خلفية بيضاء،
    مع الهامش الأبيض الذي يحتاجه القارئ (4 مربعات).
    """

    from kivy.graphics import Color, Rectangle
    from kivy.uix.widget import Widget

    class QrWidget(Widget):

        def __init__(self, matrix, **kw):

            super().__init__(**kw)

            self._matrix = matrix

            self.bind(pos=self._redraw, size=self._redraw)

            self._redraw()

        def _redraw(self, *args):

            self.canvas.clear()

            count = len(self._matrix)

            if count == 0 or self.width <= 0 or self.height <= 0:
                return

            quiet = 4

            cell = int(min(self.width, self.height) // (count + 2 * quiet))

            cell = max(cell, 1)

            side = cell * (count + 2 * quiet)

            left = self.x + (self.width - side) / 2.0
            bottom = self.y + (self.height - side) / 2.0

            with self.canvas:

                Color(1, 1, 1, 1)
                Rectangle(pos=(left, bottom), size=(side, side))

                Color(0, 0, 0, 1)

                for row_index, row in enumerate(self._matrix):

                    for col_index, dark in enumerate(row):

                        if not dark:
                            continue

                        Rectangle(
                            pos=(
                                left + (col_index + quiet) * cell,
                                bottom
                                + (count - 1 - row_index + quiet) * cell
                            ),
                            size=(cell, cell)
                        )

    return QrWidget(matrix, **kwargs)
