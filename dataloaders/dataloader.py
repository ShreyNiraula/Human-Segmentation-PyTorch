#------------------------------------------------------------------------------
#   Libraries
#------------------------------------------------------------------------------
import warnings
warnings.filterwarnings('ignore')

import cv2, os
import numpy as np
from random import shuffle

import torch
from torch.utils.data import Dataset, DataLoader

from dataloaders import transforms
# import transforms

def opticalFlowCalc(pre_img, img):
	hsv = np.zeros_like(pre_img)
	hsv[...,1] = 255

	pre_img = cv2.cvtColor(frame1,cv2.COLOR_BGR2GRAY)
	img = cv2.cvtColor(frame2,cv2.COLOR_BGR2GRAY)

	flow = cv2.calcOpticalFlowFarneback(pre_img,img, None, 0.5, 3, 15, 3, 5, 1.2, 0)
	mag, ang = cv2.cartToPolar(flow[...,0], flow[...,1])
	hsv[...,0] = ang*180/np.pi/2
	hsv[...,2] = cv2.normalize(mag,None,0,255,cv2.NORM_MINMAX)
	bgr = cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
	return bgr
#------------------------------------------------------------------------------
#	DataLoader for Semantic Segmentation
#------------------------------------------------------------------------------
class SegmentationDataLoader(object):
	def __init__(self, pairs_file, color_channel="RGB", resize=224, padding_value=0,
				crop_range=[0.75, 1.0], flip_hor=0.5, rotate=0.3, angle=10, noise_std=5,
				normalize=True, one_hot=False, is_training=True,
				shuffle=True, batch_size=1, n_workers=1, pin_memory=True):

		# Storage parameters
		super(SegmentationDataLoader, self).__init__()
		self.pairs_file = pairs_file
		self.color_channel = color_channel
		self.resize = resize
		self.padding_value = padding_value
		self.crop_range = crop_range
		self.flip_hor = flip_hor
		self.rotate = rotate
		self.angle = angle
		self.noise_std = noise_std
		self.normalize = normalize
		self.one_hot = one_hot
		self.is_training = is_training
		self.shuffle = shuffle
		self.batch_size = batch_size
		self.n_workers = n_workers
		self.pin_memory = pin_memory

		# Dataset
		self.dataset = SegmentationDataset(
			pairs_file=self.pairs_file,
			color_channel=self.color_channel,
			resize=self.resize,
			padding_value=self.padding_value,
			crop_range=self.crop_range,
			flip_hor=self.flip_hor,
			rotate=self.rotate,
			angle=self.angle,
			noise_std=self.noise_std,
			normalize=self.normalize,
			one_hot=self.one_hot,
			is_training=self.is_training,
		)

	@property
	def loader(self):
		return DataLoader(
			self.dataset,
			batch_size=self.batch_size,
			shuffle=self.shuffle,
			num_workers=self.n_workers,
			pin_memory=self.pin_memory,
		)


#------------------------------------------------------------------------------
#	Dataset for Semantic Segmentation
#------------------------------------------------------------------------------
class SegmentationDataset(Dataset):
	"""
	The dataset requires label is a grayscale image with value {0,1,...,C-1},
	where C is the number of classes.
	"""
	def __init__(self, pairs_file, color_channel="RGB", resize=512, padding_value=0,
		is_training=True, noise_std=5, crop_range=[0.75, 1.0], flip_hor=0.5, rotate=0.3, angle=10,
		one_hot=False, normalize=True, mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]):

		# Get list of image and label files
		self.prev_image_files, self.image_files, self.label_files = [], []
		fp = open(pairs_file, "r")
		lines = fp.read().split("\n")
		lines = [line.strip() for line in lines if len(line)]
		lines = [line.split(", ") for line in lines]

		print("[Dataset] Checking file paths...")
		error_flg = False
		for line in lines:
			prev_image_file, image_file, label_file = line
			if not os.path.exists(prev_image_file):
				print("%s does not exist!" % (prev_image_file))
				error_flg = True
			if not os.path.exists(image_file):
				print("%s does not exist!" % (image_file))
				error_flg = True
			if not os.path.exists(label_file):
				print("%s does not exist!" % (label_file))
				error_flg = True
			self.prev_image_files.append(prev_image_file)
			self.image_files.append(image_file)
			self.label_files.append(label_file)
		if error_flg:
			raise ValueError("Some file paths are corrupted! Please re-check your file paths!")
		print("[Dataset] Number of sample pairs:", len(self.image_files))

		# Parameters
		self.color_channel = color_channel
		self.resize = resize
		self.padding_value = padding_value
		self.is_training = is_training
		self.noise_std = noise_std
		self.crop_range = crop_range
		self.flip_hor = flip_hor
		self.rotate = rotate
		self.angle = angle
		self.one_hot = one_hot
		self.normalize = normalize
		self.mean = np.array(mean)[None,None,:]
		self.std = np.array(std)[None,None,:]

	def __len__(self):
		return len(self.image_files)

	def __getitem__(self, idx):
		# Read image and label
		prev_img_file, img_file, label_file = self.prev_image_files[idx], self.image_files[idx], self.label_files[idx]
		
		prev_image = cv2.imread(prev_img_file)[...,::-1]
		image = cv2.imread(img_file)[...,::-1]
		label = cv2.imread(label_file, 0)

		# Augmentation if in training phase
		if self.is_training:
			prev_image = transforms.random_noise(prev_image, std=self.noise_std)
			image = transforms.random_noise(image, std=self.noise_std)

			prev_image, image, label = transforms.flip_horizon(prev_image, image, label, self.flip_hor)
			prev_image, image, label = transforms.rotate_90(prev_image, image, label, self.rotate)
			prev_image, image, label = transforms.rotate_angle(prev_image, image, label, self.angle)
			prev_image, image, label = transforms.random_crop(prev_image, image, label, self.crop_range)

		# Resize: the greater side is refered, the rest is padded
		prev_image = transforms.resize_image(prev_image, expected_size=self.resize, pad_value=self.padding_value, mode=cv2.INTER_LINEAR)
		image = transforms.resize_image(image, expected_size=self.resize, pad_value=self.padding_value, mode=cv2.INTER_LINEAR)
		label = transforms.resize_image(label, expected_size=self.resize, pad_value=self.padding_value, mode=cv2.INTER_NEAREST)

		#Calculate opticalFlow
		OFlow = opticalFlowCalc(prev_image, image)

		# Preprocess image
		if self.normalize:
			OFlow = OFlow.astype(np.float32) / 255.0
			OFlow = (OFlow - self.mean) / self.std

			image = image.astype(np.float32) / 255.0
			image = (image - self.mean) / self.std

		OFlow = np.transpose(OFlow, axes=(2, 0, 1))
		image = np.transpose(image, axes=(2, 0, 1))

		# Preprocess label
		label[label>0] = 1 #here for every pixel, if the value is greater than 0 then replace it with 1
		if self.one_hot:
			label = (np.arange(label.max()+1) == label[...,None]).astype(int)

		# Convert to tensor and return
		OFlow = torch.tensor(OFlow.copy(), dtype=torch.float32)
		image = torch.tensor(image.copy(), dtype=torch.float32)
		label = torch.tensor(label.copy(), dtype=torch.float32)
		return OFlow, image, label
