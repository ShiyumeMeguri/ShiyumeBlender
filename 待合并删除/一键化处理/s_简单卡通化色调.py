import os
import sys
import glob
from PIL import Image
import numpy as np
import matplotlib.colors as mcolors

def gamma_decode(color):
    return np.power(color / 255.0, 2.2)

def gamma_encode(color):
    return np.power(color, 1/2.2) * 255

def rgb_to_hsv(rgb):
    return mcolors.rgb_to_hsv(rgb)

def hsv_to_rgb(hsv):
    return mcolors.hsv_to_rgb(hsv)

def multiply_mix(rgb, color):
    return np.clip(rgb * np.array(color[:3]), 0, 1)

def value_mix(hsv, color, fac):
    color_hsv = rgb_to_hsv(gamma_decode(np.array(color[:3])))
    facm = 1.0 - fac
    hsv[..., 2] = facm * hsv[..., 2] + fac * color_hsv[..., 2]
    return hsv_to_rgb(hsv)

def overlay_mix(col1, col2, fac):
    result = np.zeros_like(col1)
    for i in range(3):
        mask = col1[..., i] < 0.5
        result[..., i] = np.where(mask,
                                  (1-fac) * col1[..., i] + fac * (2 * col1[..., i] * col2[..., i]),
                                  (1-fac) * col1[..., i] + fac * (1 - 2 * (1 - col1[..., i]) * (1 - col2[..., i])))
    return result

def process_image(image_path, output_folder):
    img = Image.open(image_path).convert('RGBA')
    img_data = np.array(img)
    rgb_data = img_data[..., :3]
    alpha_data = img_data[..., 3]

    linear_rgb = gamma_decode(rgb_data)
    mult_color = [2, 2, 2, 1.0]
    mult_result = multiply_mix(linear_rgb, mult_color)
    hsv_data = rgb_to_hsv(mult_result)
    value_color = [0.439 * 255, 0.757 * 255, 0.961 * 255, 1.0]
    value_result = value_mix(hsv_data, value_color, 1.0)
    overlay_result = overlay_mix(mult_result, value_result, 0.5)
    final_rgb = gamma_encode(overlay_result)
    final_result = np.dstack((final_rgb, alpha_data))

    output_image = Image.fromarray(np.uint8(final_result.clip(0, 255)), 'RGBA')

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 确保使用合适的保存格式
    output_path = os.path.join(output_folder, os.path.basename(image_path))
    if output_path.lower().endswith('.jpg') or output_path.lower().endswith('.jpeg'):
        # 将RGBA转换为RGB，以便JPEG兼容
        output_image = output_image.convert('RGB')
        output_path = output_path.rsplit('.', 1)[0] + '.jpg'  # 确保扩展名正确
    else:
        output_path = output_path.rsplit('.', 1)[0] + '.png'  # 默认保存为PNG

    output_image.save(output_path)


def main(folder=None):
    if folder is None:
        folder = os.getcwd()  # Use current directory if no folder is provided
    else:
        folder = sys.argv[1]  # Use specified folder if provided
    output_folder = os.path.join(folder, 'OutputTex')

    # Support multiple image formats
    image_extensions = ('*.png', '*.jpg', '*.jpeg', '*.bmp', '*.tiff', '*.tif')
    image_files = []
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(folder, ext)))

    for image_file in image_files:
        process_image(image_file, output_folder)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main()
