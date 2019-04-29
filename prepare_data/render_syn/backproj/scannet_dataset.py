import glob
import os
import sys
import time
import imageio
import numpy as np
import multiprocessing as mp
from functools import partial
from PIL import Image
from collections import Counter


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.append(BASE_DIR)
sys.path.append(ROOT_DIR)
import dataset_utils


class ScannetDatasetTrain():
    def __init__(self, root, num_classes=21, get_depth=True, get_coord=True, point_from_depth=False):
        self.root = root
        self.num_classes = num_classes
        self.get_depth = get_depth
        self.get_coord = get_coord
        self.point_from_depth = point_from_depth
        self.data_dir = os.path.join(self.root, 'train')
        self.scene_list = glob.glob(os.path.join(self.data_dir, 'scene*'))
        print('[Dataset Train Info] Found ', len(self.scene_list), ' scenes under ', self.data_dir)
        self.labelweights = np.ones(self.num_classes)
        weight_file = os.path.join(self.root, 'class_weights.txt')
        if os.path.exists(weight_file):
            self.labelweights = dataset_utils.readClassesWeights(weight_file, self.num_classes)
        print('[Dataset Train Info] Training labelweights:\n', self.labelweights)

    def __len__(self):
        return len(self.scene_list)


    def __getitem__(self, index):
        scene_dir = self.scene_list[index]
        scene_name = os.path.basename(scene_dir)
        cam_int_param = np.loadtxt(os.path.join(scene_dir, 'intrinsic_depth.txt'))
        cam_ext_param = np.loadtxt(os.path.join(scene_dir, 'extrinsic_depth.txt'))

        label_imgs, color_imgs, depth_imgs, normal_imgs, pixcoord_imgs, pixmeta_imgs = \
            dataset_utils.get_list(scene_dir=scene_dir, label_dir='render_label', color_dir='render_color', depth_dir='render_depth', \
                     normal_dir='render_normal', pixcoord_dir='pixel_coord', pixmeta_dir='pixel_meta', \
                     label_ext='png', color_ext='jpg', depth_ext='npz', normal_ext='npz', \
                     pixcoord_ext='npz', pixmeta_ext='npz')

        num_sample = 0
        while num_sample < 10:
            rand_img_idx = np.random.randint(low=0, high=len(label_imgs))
            color_img, depth_img, pixel_label, pixel_weight, label_set = \
                dataset_utils.get_image_sample(self.labelweights, color_imgs[rand_img_idx], depth_imgs[rand_img_idx], label_imgs[rand_img_idx], self.get_depth)
            if self.get_coord is True:
                ext_param = np.matmul(ext_param, cam_ext_param)
                translation = ext_param[0:3, 3] # [0,3], [1,3], [2,3]
                rotation = ext_param[0:3, 0:3]
                if self.point_from_depth is True:
                    coord_img, coord_label, coord_weight, valid_coord_idx = \
                        dataset_utils.get_depth_coord_sample(self.labelweights, \
                                                color_imgs[rand_img_idx], depth_imgs[rand_img_idx], label_imgs[rand_img_idx], \
                                                cam_int_param, rotation, translation)
                else: # load from pixcoord
                    coord_img, coord_label, coord_weight, valid_coord_idx = \
                        dataset_utils.get_coord_sample(self.labelweights, \
                                          color_imgs[rand_img_idx], pixcoord_imgs[rand_img_idx], label_imgs[rand_img_idx], \
                                          cam_int_param, rotation, translation)
            else:
                coord_img = np.zeros((color_img.shape[0], color_img.shape[1], 6))
                coord_label = np.zeros(pixel_label.shape)
                coord_weight = np.zeros(pixel_weight.shape)
                valid_coord_idx = np.zeros((pixel_weight.shape[0], pixel_weight.shape[1]))
            num_sample += 1
            if len(label_set) >= 2: # valid sample
                break
        return scene_name, \
               color_img, depth_img, pixel_label, pixel_weight, \
               coord_img, coord_label, coord_weight, valid_coord_idx



class ScannetDatasetVal():
    def __init__(self, root, num_classes=21, split='val', \
                 get_depth=True, get_coord=True, get_pixmeta=False, point_from_depth=False, with_scene_point=False, \
                 frame_skip=1, num_proc=20):
        self.root = root
        self.split = split
        self.get_depth = get_depth
        self.get_coord = get_coord
        self.get_pixmeta = get_pixmeta
        self.point_from_depth = point_from_depth
        self.with_scene_point = with_scene_point
        self.num_classes = num_classes
        self.frame_skip = frame_skip
        self.pool = mp.Pool(num_proc)
        self.data_dir = os.path.join(self.root, '%s'%self.split)
        self.scene_list = glob.glob(os.path.join(self.data_dir, 'scene*'))
        print('[Dataset Val Info] Found ', len(self.scene_list), ' scenes under ', self.data_dir)
        self.labelweights = np.ones(self.num_classes)
        weight_file = os.path.join(self.root, 'class_weights.txt')
        if os.path.exists(weight_file):
            self.labelweights = dataset_utils.readClassesWeights(weight_file, self.num_classes)
        print('[Dataset Val Info] Training labelweights:\n', self.labelweights)

    def __len__(self):
        return len(self.scene_list)


    def __getitem__(self, index):
        start_time = time.time()
        scene_dir = self.scene_list[index]
        scene_name = os.path.basename(scene_dir)
        cam_int_param = np.loadtxt(os.path.join(scene_dir, 'intrinsic_depth.txt'))
        cam_ext_param = np.loadtxt(os.path.join(scene_dir, 'extrinsic_depth.txt'))
        scene_point = None
        if self.with_scene_point is True:
            scene_point = np.load(os.path.join(scene_dir, scene_name+'.npy'))

        label_imgs, color_imgs, depth_imgs, normal_imgs, pixcoord_imgs, pixmeta_imgs = \
            dataset_utils.get_list(scene_dir=scene_dir, label_dir='pseudo_pose_label', color_dir='pseudo_pose_color', depth_dir='pseudo_pose_depth', \
                     normal_dir='pseudo_pose_normal', pixcoord_dir='pseudo_pose_pixel_coord', pixmeta_dir='pseudo_pose_pixel_meta',\
                     label_ext='png', color_ext='jpg', depth_ext='npz', normal_ext='npz', \
                     pixcoord_ext='npz', pixmeta_ext='npz')

        data_dir = zip(label_imgs[::self.frame_skip], color_imgs[::self.frame_skip], \
                       depth_imgs[::self.frame_skip], normal_imgs[::self.frame_skip], \
                       pixcoord_imgs[::self.frame_skip], pixmeta_imgs[::self.frame_skip])
        get_scene_data = partial(dataset_utils.get_scene_data, 
                                 self.labelweights, 
                                 cam_int_param,
                                 self.get_depth,
                                 self.get_coord,
                                 self.get_pixmeta,
                                 self.point_from_depth)
        res = self.pool.map(get_scene_data, data_dir)
        
        color_img_list, depth_img_list, pixel_label_list, pixel_weight_list, \
        coord_img_list, coord_label_list, coord_weight_list, valid_coord_idx_list, \
        pixel_meta_list = map(list, zip(*res))
        
        print('get {} time {}'.format(scene_name, time.time()-start_time))
        scene_data = {
            'scene_name': scene_name, 
            'scene_point': scene_point, 
            'num_view': len(color_img_list),
            'pixel_meta_list': pixel_meta_list,
            'color_img_list': color_img_list, 
            'depth_img_list': depth_img_list, 
            'pixel_label_list': pixel_label_list, 
            'pixel_weight_list': pixel_weight_list, 
            'coord_img_list': coord_img_list,
            'coord_label_list': coord_label_list,
            'coord_weight_list': coord_weight_list,
            'valid_coord_idx_list': valid_coord_idx_list
        }    
        return scene_data

class ScannetDatasetSeqVal():
    def __init__(self, root, num_classes=21, split='val', get_depth=True, get_coord=True, get_pixmeta=False, point_from_depth=False, with_scene_point=False, frame_skip=1):
        self.root = root
        self.split=split
        self.get_depth = get_depth
        self.get_coord = get_coord
        self.get_pixmeta = get_pixmeta
        self.point_from_depth = point_from_depth
        self.with_scene_point = with_scene_point
        self.frame_skip = frame_skip
        self.num_classes = num_classes
        self.data_dir = os.path.join(self.root, '%s'%self.split)
        self.scene_list = glob.glob(os.path.join(self.data_dir, 'scene*'))
        print('[Dataset Val Info] Found ', len(self.scene_list), ' scenes under ', self.data_dir)
        self.labelweights = np.ones(self.num_classes)
        weight_file = os.path.join(self.root, 'class_weights.txt')
        if os.path.exists(weight_file):
            self.labelweights = dataset_utils.readClassesWeights(weight_file, self.num_classes)
        print('[Dataset Val Info] Training labelweights:\n', self.labelweights)

    def __len__(self):
        return len(self.scene_list)


    def __getitem__(self, index):
        start_time = time.time()
        scene_dir = self.scene_list[index]
        scene_name = os.path.basename(scene_dir)
        cam_int_param = np.loadtxt(os.path.join(scene_dir, 'intrinsic_depth.txt'))
        cam_ext_param = np.loadtxt(os.path.join(scene_dir, 'extrinsic_depth.txt'))
        scene_point = None
        if self.with_scene_point is True:
            scene_point = np.load(os.path.join(scene_dir, scene_name+'.npy'))

        label_imgs, color_imgs, depth_imgs, normal_imgs, pixcoord_imgs, pixmeta_imgs = \
            dataset_utils.get_list(scene_dir=scene_dir, label_dir='render_label', color_dir='render_color', depth_dir='render_depth', \
                     normal_dir='render_normal', pixcoord_dir='pixel_coord', pixmeta_dir='pixel_meta', \
                     label_ext='png', color_ext='jpg', depth_ext='npz', normal_ext='npz', \
                     pixcoord_ext='npz', pixmeta_ext='npz')

        color_img_list = list()
        depth_img_list = list()
        pixel_label_list = list()
        pixel_weight_list = list()
        coord_img_list = list()
        coord_label_list = list()
        coord_weight_list = list()
        valid_coord_idx_list = list()
        pixel_meta_list = list()

        data_dir = zip(label_imgs, color_imgs, depth_imgs, normal_imgs, pixcoord_imgs, pixmeta_imgs)
        
        for i in range(0, len(label_imgs), self.frame_skip):
            color_img, depth_img, pixel_label, pixel_weight, label_set = \
                dataset_utils.get_image_sample(self.labelweights, color_imgs[i], depth_imgs[i], label_imgs[i], self.get_depth)
            #print(color_img.shape, depth_img.shape, pixel_label.shape, pixel_weight.shape)
            if self.get_coord is True:
                ext_param = np.matmul(ext_param, cam_ext_param)
                translation = ext_param[0:3, 3] # [0,3], [1,3], [2,3]
                rotation = ext_param[0:3, 0:3]
                if self.point_from_depth is True:
                    coord_img, coord_label, coord_weight, valid_coord_idx = \
                        dataset_utils.get_depth_coord_sample(self.labelweights, \
                                                color_imgs[i], depth_imgs[i], label_imgs[i], \
                                                cam_int_param, rotation, translation)
                else: # load from pixcoord
                    coord_img, coord_label, coord_weight, valid_coord_idx = \
                        dataset_utils.get_coord_sample(self.labelweights, \
                                          color_imgs[i], pixcoord_imgs[i], label_imgs[i], \
                                          cam_int_param, rotation, translation)
                if self.get_pixmeta is True:
                    pixel_world_coord = np.load(pixcoord_imgs[i])['pixcoord']  # load depth
                    pixel_meta = np.load(pixmeta_imgs[i])['meta']
                    pixel_meta = np.concatenate([pixel_world_coord, pixel_meta], axis=-1)
                    pixel_meta_list.append(np.expand_dims(pixel_meta, axis=0))
            else:
                coord_img = np.zeros((color_img.shape[0], color_img.shape[1], 6))
                coord_label = np.zeros(pixel_label.shape)
                coord_weight = np.zeros(pixel_weight.shape)
                valid_coord_idx = np.zeros((pixel_weight.shape[0], pixel_weight.shape[1]))

            color_img_list.append(np.expand_dims(color_img, axis=0))
            depth_img_list.append(np.expand_dims(depth_img, axis=0))
            pixel_label_list.append(np.expand_dims(pixel_label, axis=0))
            pixel_weight_list.append(np.expand_dims(pixel_weight, axis=0))
            coord_img_list.append(np.expand_dims(coord_img, axis=0))
            coord_label_list.append(np.expand_dims(coord_label, axis=0))
            coord_weight_list.append(np.expand_dims(coord_weight, axis=0))
            valid_coord_idx_list.append(np.expand_dims(valid_coord_idx, axis=0))
        print('get {} time {}'.format(scene_name, time.time()-start_time))
            
        scene_data = {
            'scene_name': scene_name, 
            'scene_point': scene_point, 
            'num_view': len(color_img_list),
            'pixel_meta_list': pixel_meta_list,
            'color_img_list': color_img_list, 
            'depth_img_list': depth_img_list, 
            'pixel_label_list': pixel_label_list, 
            'pixel_weight_list': pixel_weight_list, 
            'coord_img_list': coord_img_list,
            'coord_label_list': coord_label_list,
            'coord_weight_list': coord_weight_list,
            'valid_coord_idx_list': valid_coord_idx_list
        }    
        return scene_data


if __name__ == "__main__":
    from utils import vis_utils
    d = ScannetDatasetTrain(root = '/tmp3/hychiang/scannetv2_preprocess', point_from_depth=True)
    #d = ScannetDatasetTrain(root = '/tmp3/hychiang/scannetv2_preprocess', point_from_depth=False)
    #d = ScannetDatasetTrain(root = '/tmp3/hychiang/scannetv2_preprocess', get_depth=False, get_coord=False)
    start_time = time.time()
    for i in range(5):
        scene_name, color_img, depth_img, pixel_label, pixel_weight, \
        coord_img, coord_label, coord_weight, valid_coord_idx = d[i]
        print(scene_name, color_img.shape, depth_img.shape, pixel_label.shape, pixel_weight.shape, \
              coord_img.shape, coord_label.shape, coord_weight.shape, valid_coord_idx.shape)
        #vis_utils.dump_point_cloud(
        #    scene_name=scene_name, 
        #    output_dir='../dataset_vis', 
        #    coord_img=coord_img, 
        #    valid_coord_idx=valid_coord_idx, 
        #    coord_label=coord_label, 
        #    coord_weight=coord_weight 
        #) 
        #vis_utils.dump_images(
        #    scene_name=scene_name,
        #    output_dir='../dataset_vis',
        #    color_img=color_img,
        #    depth_img=depth_img,
        #    pixel_label=pixel_label,
        #    pixel_weight=pixel_weight
        #)

    print('Load all training scenes: ', time.time()-start_time)

    #d = ScannetDatasetVal(root = '../', point_from_depth=True, frame_skip=5)
    #d = ScannetDatasetVal(root = '/tmp3/hychiang/scannetv2_preprocess', point_from_depth=False, frame_skip=5)
    #d = ScannetDatasetVal(root = '/tmp3/hychiang/scannetv2_preprocess', get_depth=False, get_coord=False, get_pixmeta=False, point_from_depth=False, frame_skip=5)
    #d = ScannetDatasetVal(root = '/tmp3/hychiang/scannetv2_preprocess', get_depth=True, get_coord=True, get_pixmeta=True, point_from_depth=False, frame_skip=5)
    #d = ScannetDatasetVal(root = '/tmp3/hychiang/scannetv2_preprocess', get_depth=False, get_coord=False, get_pixmeta=False, point_from_depth=False)
    d = ScannetDatasetVal(root = '/tmp3/hychiang/scannetv2_preprocess', get_depth=True, get_coord=True, get_pixmeta=True, point_from_depth=False)
    start_time = time.time()
    for i in range(5):
        scene_data = d[i]
        print(scene_data['scene_name'], len(scene_data['pixel_meta_list']), \
              len(scene_data['color_img_list']), len(scene_data['depth_img_list']), \
              len(scene_data['pixel_label_list']), len(scene_data['pixel_weight_list']), \
              len(scene_data['coord_img_list']), len(scene_data['coord_label_list']), \
              len(scene_data['coord_weight_list']), len(scene_data['valid_coord_idx_list']))
    d = ScannetDatasetVal(root = '/tmp3/hychiang/scannetv2_preprocess', get_depth=True, get_coord=True, get_pixmeta=True, point_from_depth=False, frame_skip=5)
    print('Load all valid scenes with pixel meta, step=1: ', time.time()-start_time)


    start_time = time.time()
    for i in range(5):
        scene_data = d[i]
        print(scene_data['scene_name'], len(scene_data['pixel_meta_list']), \
              len(scene_data['color_img_list']), len(scene_data['depth_img_list']), \
              len(scene_data['pixel_label_list']), len(scene_data['pixel_weight_list']), \
              len(scene_data['coord_img_list']), len(scene_data['coord_label_list']), \
              len(scene_data['coord_weight_list']), len(scene_data['valid_coord_idx_list']))
        #vis_utils.dump_point_cloud(
        #    scene_name=scene_data['scene_name'], 
        #    output_dir='../dataset_vis', 
        #    coord_img=np.squeeze(scene_data['coord_img_list'][0], axis=0), 
        #    valid_coord_idx=np.squeeze(scene_data['valid_coord_idx_list'][0], axis=0) , 
        #    coord_label=np.squeeze(scene_data['coord_label_list'][0], axis=0) , 
        #    coord_weight=np.squeeze(scene_data['coord_weight_list'][0], axis=0) 
        #) 

        #vis_utils.dump_images(
        #    scene_name=scene_data['scene_name'],
        #    output_dir='../dataset_vis',
        #    color_img=np.squeeze(scene_data['color_img_list'][0], axis=0),
        #    depth_img=np.squeeze(scene_data['depth_img_list'][0], axis=0),
        #    pixel_label=np.squeeze(scene_data['pixel_label_list'][0], axis=0),
        #    pixel_weight=np.squeeze(scene_data['pixel_weight_list'][0], axis=0)
        #)
    print('Load all valid scenes with pixel meta, step=5: ', time.time()-start_time)