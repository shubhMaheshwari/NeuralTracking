# The code in this contains methods to load data and generate deformable graph for Fusion Experiments 

# Library imports	
import os
import json
import numpy as np
from scipy.io import loadmat 

# Modules
from model import dataset
import options as opt
from utils import image_proc

# Modules for Fusion
from create_graph_data_using_depth import create_graph_data_using_depth


class RGBDVideoLoader:
	def __init__(self, seq_dir):
		
		# Find the sequence split and name of the sequence 
		self.seq_dir = seq_dir
		self.split, self.seq_name = list(filter(lambda x: x != '', seq_dir.split('/')))[-2:]
		# Load internics matrix
		intrinsics_matrix = np.loadtxt(os.path.join(seq_dir, "intrinsics.txt"))
		self.intrinsics = {
			"fx": intrinsics_matrix[0, 0],
			"fy": intrinsics_matrix[1, 1],
			"cx": intrinsics_matrix[0, 2],
			"cy": intrinsics_matrix[1, 2]
		}

		self.images_path = list(sorted(os.listdir(os.path.join(seq_dir, "color")), key=lambda x: int(x.split('.')[0])  ))

		# Parameters for generating new graph
		if os.path.isfile(os.path.join(self.seq_dir,'graph_config.json')):
			with open(os.path.join(self.seq_dir,'graph_config.json')) as f:
				self.graph_generation_parameters = json.load(f)	

		else: # Defualt case
			self.graph_generation_parameters = {
				# Given a depth image, its mesh is constructed by joining using its adjecent pixels, 
				# based on the depth values, a perticular vertex could be far away from its adjacent pairs in for a particular face/triangle
				# `max_triangle_distance` controls this. For a sperical surfaces (such as a dolls, human body) this should be set high. But for clothes this can be small      
				'max_triangle_distance' : 0.05, 
				'erosion_num_iterations': 10, # Will reduce outliers points (simliar to erosion in images)
				'erosion_min_neighbors' : 4, # Will reduce outlier clusters
				'node_coverage'		   	: 0.05, # Sampling parameter which defines the number of nodes
				'require_mask'			: True,
				}

		# Load all types of data avaible
		self.graph_dicts = {}
		if os.path.isdir(os.path.join(seq_dir,"graph_nodes")):
			for file in os.listdir(os.path.join(seq_dir,"graph_nodes")):
			
				file_data = file[:-4].split('_')
				if len(file_data) == 4: # Using our setting frame_<frame_index>_geodesic_<node_coverage>.bin
					frame_index = int(file_data[1])
					node_coverage = float(file_data[-1])
				elif len(file_data) == 6: # Using name setting used by authors <random_str>_<Obj-Name>_<Source-Frame-Index>_<Target-Frame-Index>_geodesic_<Node-Coverage>.bin
					frame_index = int(file_data[2])
					node_coverage = float(file_data[-1])
				else:
					raise NotImplementedError(f"Unable to understand file:{file} to get graph data")

				self.graph_dicts[frame_index] = {}
				self.graph_dicts[frame_index]["graph_nodes_path"]             = os.path.join(seq_dir, "graph_nodes",        file)
				self.graph_dicts[frame_index]["graph_edges_path"]             = os.path.join(seq_dir, "graph_edges",        file)
				self.graph_dicts[frame_index]["graph_edges_weights_path"]     = os.path.join(seq_dir, "graph_edges_weights",file)
				self.graph_dicts[frame_index]["graph_clusters_path"]          = os.path.join(seq_dir, "graph_clusters",     file)
				self.graph_dicts[frame_index]["pixel_anchors_path"]           = os.path.join(seq_dir, "pixel_anchors",      file)
				self.graph_dicts[frame_index]["pixel_weights_path"]           = os.path.join(seq_dir, "pixel_weights",      file)
				self.graph_dicts[frame_index]["node_coverage"] 		          = node_coverage

		self.savepath = os.path.join(self.seq_dir,"results")
		if not os.path.isdir(self.savepath):
			os.mkdir(self.savepath)

			os.mkdir(os.path.join(self.savepath,"deformation"))
			os.mkdir(os.path.join(self.savepath,"updated_graph"))
			os.mkdir(os.path.join(self.savepath,"tsdf"))
			os.mkdir(os.path.join(self.savepath,"canonical_model"))
			os.mkdir(os.path.join(self.savepath,"deformed_model"))
			
			os.mkdir(os.path.join(self.savepath,"images"))
			os.mkdir(os.path.join(self.savepath,"video"))


	def get_frame_path(self,index):
		# Return the path to color, depth and mask
		return os.path.join(self.seq_dir,"color",self.images_path[index]),\
			os.path.join(self.seq_dir,"depth",self.images_path[index].replace('jpg','png')),\
			os.path.join(self.seq_dir,"mask",self.images_path[index].replace('jpg','png'))


	def get_source_data(self,source_frame):
		# Source color and depth
		src_color_image_path,src_depth_image_path,_ = self.get_frame_path(source_frame)
		source, _, cropper = dataset.DeformDataset.load_image(
			src_color_image_path, src_depth_image_path, self.intrinsics, opt.image_height, opt.image_width)

		# Update intrinsics to reflect the crops
		fx, fy, cx, cy = image_proc.modify_intrinsics_due_to_cropping(
			self.intrinsics['fx'], self.intrinsics['fy'], self.intrinsics['cx'], self.intrinsics['cy'], 
			opt.image_height, opt.image_width, original_h=cropper.h, original_w=cropper.w)

		intrinsics_cropped = np.zeros((4), dtype=np.float32)
		intrinsics_cropped[0] = fx
		intrinsics_cropped[1] = fy
		intrinsics_cropped[2] = cx
		intrinsics_cropped[3] = cy

		source_data = {}
		source_data["source"]				= source
		source_data["cropper"]				= cropper
		source_data["intrinsics"]			= intrinsics_cropped

		return source_data


	def get_target_data(self,target_frame,cropper):
		# Target color and depth (and boundary mask)
		tgt_color_image_path,tgt_depth_image_path,tgt_depth_mask_path = self.get_frame_path(target_frame)
		target, target_boundary_mask, _ = dataset.DeformDataset.load_image(
			tgt_color_image_path, tgt_depth_image_path, self.intrinsics, opt.image_height, opt.image_width, cropper=cropper,
			max_boundary_dist=opt.max_boundary_dist, compute_boundary_mask=True)

		target_data = {}
		target_data["target_index"]			= target_frame

		target_data["target"]				= target
		target_data["target_boundary_mask"]	= target_boundary_mask
		target_data["target_mask"] 			= dataset.DeformDataset.load_mask(tgt_depth_mask_path) # Mask for target frame if avaible else None

		return target_data 				
	def get_graph_path(self,index):
		"""
			This function returns the paths to the graph generated for a particular frame, and geodesic distance (required for sampling nodes, estimating edge weights etc.)
		"""

		if index not in self.graph_dicts:
			self.graph_dicts[index] = create_graph_data_using_depth(\
				os.path.join(self.seq_dir,"depth",self.images_path[index].replace('jpg','png')),\
				max_triangle_distance=self.graph_generation_parameters['max_triangle_distance'],\
				erosion_num_iterations=self.graph_generation_parameters['erosion_num_iterations'],\
				erosion_min_neighbors=self.graph_generation_parameters['erosion_min_neighbors'],\
				node_coverage=self.graph_generation_parameters['node_coverage'],\
				require_mask=self.graph_generation_parameters['require_mask']
				)

		return self.graph_dicts[index]

	def get_graph(self,index,cropper):
		# Graph
		graph_path_dict = self.get_graph_path(index)

		graph_nodes, graph_edges, graph_edges_weights, _, graph_clusters, pixel_anchors, pixel_weights = dataset.DeformDataset.load_graph_data(
			graph_path_dict["graph_nodes_path"], graph_path_dict["graph_edges_path"], graph_path_dict["graph_edges_weights_path"], None, 
			graph_path_dict["graph_clusters_path"], graph_path_dict["pixel_anchors_path"], graph_path_dict["pixel_weights_path"], cropper
		)

		num_nodes = np.array(graph_nodes.shape[0], dtype=np.int64)	

		graph_dict = {}
		graph_dict["graph_nodes"]				= graph_nodes
		graph_dict["graph_edges"]				= graph_edges
		graph_dict["graph_edges_weights"]		= graph_edges_weights
		graph_dict["graph_clusters"]			= graph_clusters
		graph_dict["pixel_weights"]				= pixel_weights
		graph_dict["pixel_anchors"]				= pixel_anchors
		graph_dict["num_nodes"]					= num_nodes
		graph_dict["node_coverage"]				= graph_path_dict["node_coverage"]
		graph_dict["graph_neighbours"]			= min(len(graph_nodes),4) 
		return graph_dict

	def get_video_length(self):
		return len(self.images_path)


	def load_dict(self,path):
		data = loadmat(path)
		model_data = {}
		for k in data: 
			if '__' in k:
				continue
			else:
				model_data[k] = np.array(data[k])
				if model_data[k].shape == (1,1):
					model_data[k] = np.array(model_data[k][0,0])
		return model_data	