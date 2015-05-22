import sys
import os
import getopt
import subprocess
import re
import time
import csv
import numpy as np
from scipy.misc import imread
from tifffile import imsave
from scipy.ndimage.measurements import histogram
from collections import OrderedDict
from collections import defaultdict
from control_class import Base
from control_class import Directory
from control_class import File
from socket_client import Client

def usage():
    """Usage function to help user start the script"""

    print("""Usage: """+sys.argv[0]+""" -i <dir> [options]

    Options and arguments:
    -h, --help                  : show the usage information
    -i <dir>, --input=<dir>     : set imaging directory
    --wdir=<dir>                : set working directory
    --std=<well>                : set standard well
    --firstgain=<gain_file>     : set first initial gains file
    --secondgain=<gain_file>    : set second initial gains file
    --finwell=<well>            : set final well
    --finfield=<field>          : set final field
    --coords=<file>             : set 63x coordinates file
    --host=<ip>                 : set host ip address""")

def camstart_com(_afjob, _afr, _afs):
    """Returns a cam command to start the cam scan with selected AF job
    and AF settings."""

    _com = ('/cli:1 /app:matrix /cmd:startcamscan /runtime:36000'
            ' /repeattime:36000 /afj:'+_afjob+' /afr:'+_afr+' /afs:'+_afs)
    return _com

def gain_com(_job, _pmt, _gain):
    """Returns a cam command for changing the pmt gain in a job."""

    _com = ('/cli:1 /app:matrix /cmd:adjust /tar:pmt /num:'+_pmt+
            ' /exp:'+_job+' /prop:gain /value:'+_gain
            )
    return _com

def get_wfx(_compartment):
    """Returns a string representing the well or field X coordinate."""

    return str(int(re.sub(r'\D', '', re.sub('--.\d\d', '', _compartment)))+1)

def get_wfy(_compartment):
    """Returns a string representing the well or field Y coordinate."""

    return str(int(re.sub(r'\D', '', re.sub('.\d\d--', '', _compartment)))+1)

def enable_com(_well, _field, enable):
    """Returns a cam command to enable a field in a well."""

    wellx = get_wfx(_well)
    welly = get_wfy(_well)
    fieldx = get_wfx(_field)
    fieldy = get_wfy(_field)
    _com = ('/cli:1 /app:matrix /cmd:enable /slide:0 /wellx:'+wellx+
            ' /welly:'+welly+' /fieldx:'+fieldx+' /fieldy:'+fieldy+
            ' /value:'+enable)
    return _com

def cam_com(_job, _well, _field, _dx, _dy):
    """Returns a cam command to add a field to the cam list."""

    _wellx = get_wfx(_well)
    _welly = get_wfy(_well)
    _fieldx = get_wfx(_field)
    _fieldy = get_wfy(_field)
    _com = ('/cli:1 /app:matrix /cmd:add /tar:camlist /exp:'+_job+
            ' /ext:af /slide:0 /wellx:'+_wellx+' /welly:'+_welly+
            ' /fieldx:'+_fieldx+' /fieldy:'+_fieldy+' /dxpos:'+_dx+
            ' /dypos:'+_dy
            )
    return _com

def process_output(well, output, dict_list):
    """Function to process output from the R scripts."""
    for c in output.split():
        dict_list[well].append(c)
    return dict_list

def read_csv(path, index, keys, dict):
    """Read a csv file and return a dictionary of lists."""
    with open(path) as f:
        reader = csv.DictReader(f)
        for d in reader:
            for key in keys:
                dict[d[index]].append(d[key])
    return dict

def write_csv(path, list_dicts, keys):
    """Function to write a list of dicts as a csv file."""

    with open(path, 'wb') as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(list_dicts)

def make_proj(img_list):
    """Function to make a dict of max projections from a list of paths
    to images. Each channel will make one max projection"""
    channels = []
    try:
        ptime = time.time()
        for path in img_list:
            channel = File(path).get_name('C\d\d')
            channels.append(channel)
            channels = sorted(set(channels))
        max_imgs = {}
        for channel in channels:
            images = []
            for path in img_list:
                if channel == File(path).get_name('C\d\d'):
                    images.append(imread(path))
            max_imgs[channel] = np.maximum.reduce(images)
        print('Max proj:'+str(time.time()-ptime)+' secs')
        return max_imgs
    except IndexError as e:
        print('No images to produce max projection.' , e)

def get_imgs(path, imdir, job_order, img_save=None, csv_save=None):
    if img_save is None:
        img_save = True
    if csv_save is None:
        csv_save = True
    img_paths = Directory(path).get_all_files('*'+job_order+'*.tif')
    new_paths = []
    metadata_d = {}
    for img_path in img_paths:
        img = File(img_path)
        image = imread(img_path)
        well = img.get_name('U\d\d--V\d\d')
        job_order = img.get_name('E\d\d')
        field = img.get_name('X\d\d--Y\d\d')
        z_slice = img.get_name('Z\d\d')
        channel = img.get_name('C\d\d')
        if job_order == 'E01':
            new_name = path+'/'+well+'--'+field+'--'+z_slice+'--C00.ome.tif'
            channel = 'C00'
        elif job_order == 'E02' and channel == 'C00':
            new_name = path+'/'+well+'--'+field+'--'+z_slice+'--C01.ome.tif'
            channel = 'C01'
        elif job_order == 'E02' and channel == 'C01':
            new_name = path+'/'+well+'--'+field+'--'+z_slice+'--C02.ome.tif'
            channel = 'C02'
        elif job_order == 'E03':
            new_name = path+'/'+well+'--'+field+'--'+z_slice+'--C03.ome.tif'
            channel = 'C03'
        else:
            new_name = img_path
        if len(image) == 512 or len(image) == 2048:
            new_paths.append(new_name)
            metadata_d[well+'--'+field+'--'+channel] = img.meta_data()
        os.rename(img_path, new_name)
    max_projs = make_proj(new_paths)
    new_dir = imdir+'/maxprojs/'
    if not os.path.exists(new_dir):
        os.makedirs(new_dir)
    for channel, proj in max_projs.iteritems():
        ptime = time.time()
        if img_save:
            p = new_dir+'image--'+well+'--'+field+'--'+channel+'.tif'
            metadata = metadata_d[well+'--'+field+'--'+channel]
            imsave(p, proj, description=metadata)
        if csv_save:
            if proj.dtype.name == 'uint8':
                max_int = 255
            if proj.dtype.name == 'uint16':
                max_int = 65535
            histo = histogram(proj, 0, max_int, 256)
            rows = []
            for b, count in enumerate(histo):
                rows.append({'bin': b, 'count': count})
            p = new_dir+well+'--'+channel+'.ome.csv'
            write_csv(os.path.normpath(p), rows, ['bin', 'count'])
        print('Save image:'+str(time.time()-ptime)+' secs')
    return

def main(argv):
    """Main function"""

    try:
        opts, args = getopt.getopt(argv, 'hi:', ['help',
                                                 'input=',
                                                 'wdir=',
                                                 'std=',
                                                 'firstgain=',
                                                 'secondgain=',
                                                 'finwell=',
                                                 'finfield=',
                                                 'coords=',
                                                 'host=',
                                                 'inputgain='
                                                 ])
    except getopt.GetoptError as e:
        print e
        usage()
        sys.exit(2)

    if not opts:
        usage()
        sys.exit(0)

    imaging_dir = ''
    working_dir = os.path.dirname(os.path.abspath(__file__))
    std_well = 'U00--V00'
    first_initialgains_file = os.path.normpath(working_dir+'/10x_gain.csv')
    sec_initialgains_file = os.path.normpath(working_dir+'/40x_gain.csv')
    last_well = 'U00--V00'
    last_field = 'X01--Y01'
    coord_file = None
    sec_gain_file = None
    host = ''
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            usage()
            sys.exit()
        elif opt in ('-i', '--input'):
            imaging_dir = os.path.normpath(arg)
        elif opt in ('--wdir'):
            working_dir = os.path.normpath(arg)
        elif opt in ('--std'):
            std_well = arg # 'U00--V00'
        elif opt in ('--firstgain'):
            first_initialgains_file = os.path.normpath(arg)
        elif opt in ('--secondgain'):
            sec_initialgains_file = os.path.normpath(arg)
        elif opt in ('--finwell'):
            last_well = arg # 'U00--V00'
        elif opt in ('--finfield'):
            last_field = arg # 'X00--Y00'
        elif opt in ('--coords'):
            coord_file = os.path.normpath(arg) #
        elif opt in ('--host'):
            host = arg
        elif opt in ('--inputgain'):
            sec_gain_file = arg
        else:
            assert False, 'Unhandled option!'

    # Paths
    first_r_script = os.path.normpath(working_dir+'/gain.r')
    sec_r_script = os.path.normpath(working_dir+'/gain_change_objectives.r')

    # Job names
    af_job_10x = 'af10xcam'
    afr_10x = '200'
    afs_10x = '41'
    af_job_40x = 'af40x'
    afr_40x = '105'
    afs_40x = '106'
    af_job_63x = 'af63x'
    afr_63x = '50'
    afs_63x = '51'
    g_job_10x = 'gain10x'
    g_job_40x = 'gain40x'
    g_job_63x = 'gain63x'
    job_40x = ['job7', 'job8', 'job9']
    pattern_40x = ['pattern2']
    job_63x = ['job10', 'job11', 'job12', 'job13', 'job14', 'job15',
               'job16', 'job17', 'job18', 'job19', 'job20', 'job21']
    pattern_63x = ['pattern3', 'pattern4', 'pattern5', 'pattern6']
    job_dummy = 'job22'

    # Booleans to control flow.
    stage0 = True
    stage1 = True
    stage1after = False
    stage2before = True
    stage2_40x_before = True
    stage2_63x_before = False
    stage2after = False
    stage3 = True
    stage4 = False
    stage5 = False
    if coord_file:
        stage1after = True
        stage2_40x_before = False
        stage2_63x_before = True
        stage3 = False
        stage4 = True
        coords = defaultdict(list)
        coords = read_csv(coord_file, 'fov', ['dxPx', 'dyPx'], coords)

    # 10x gain job cam command in all selected wells
    stage1_com = '/cli:1 /app:matrix /cmd:deletelist\n'
    for u in range(int(get_wfx(last_well))):
        for v in range(int(get_wfy(last_well))):
            for i in range(2):
                stage1_com = (stage1_com +
                              cam_com(g_job_10x,
                                      'U0'+str(u)+'--V0'+str(v),
                                      'X0'+str(i)+'--Y0'+str(i),
                                      '0',
                                      '0'
                                      )+
                              '\n')

    # 40x gain job cam command in standard well
    stage2_40x = ('/cli:1 /app:matrix /cmd:deletelist\n'+
                  cam_com(g_job_40x, std_well, 'X00--Y00', '0', '0')+
                  '\n'+
                  cam_com(g_job_40x, std_well, 'X01--Y01', '0', '0'))

    # 63x gain job cam command in standard well
    stage2_63x = ('/cli:1 /app:matrix /cmd:deletelist\n'+
                  cam_com(g_job_63x, std_well, 'X00--Y00', '0', '0')+
                  '\n'+
                  cam_com(g_job_63x, std_well, 'X01--Y01', '0', '0'))

    start_com = '/cli:1 /app:matrix /cmd:startscan\n'
    stop_com = '/cli:1 /app:matrix /cmd:stopscan\n'
    stop_cam_com = '/cli:1 /app:matrix /cmd:stopcamscan\n'

    # Create imaging directory object
    img_dir = Directory(imaging_dir)

    # Create socket
    sock = Client()
    # Port number
    port = 8895
    # Connect to server
    sock.connect(host, port)

    # timeout
    timeout = 300
    # start time
    begin = time.time()

    # Path to standard well from second objective.
    sec_std_path = ''

    # lists for keeping csv file base path names and
    # corresponding well names
    filebases = []
    first_std_fbs = []
    sec_std_fbs = []
    fin_wells = []

    first_gain_dict = defaultdict(list)
    sec_gain_dict = defaultdict(list)

    if sec_gain_file:
        stage0 = False

    while stage0:
        print('stage0')
        print('Time: '+str(time.time()-begin)+' secs')
        if ((time.time()-begin) > timeout):
            print('Timeout! No more images to process!')
            break
        print('Waiting for images...')
        try:
            #if stage1:
            #    print('Stage1')
            #    # Add 10x gain scan for wells to CAM list.
            #    sock.send(stage1_com)
            #    # Start scan.
            #    print(start_com)
            #    sock.send(start_com)
            #    time.sleep(3)
            #    cstart = camstart_com(af_job_10x, afr_10x, afs_10x)
            #    # Start CAM scan.
            #    print(cstart)
            #    # Start CAM scan.
            #    sock.send(cstart)
            #    stage1 = False
            reply = sock.recv_timeout(40, ['image--'])
            # Parse reply, check well (UV), field (XY).
            # Get well path.
            # Get all image paths in well.
            # Make a max proj per channel and well.
            # Save meta data and image max proj.
            if 'E00' in reply:
                img_name = File(reply).get_name('image--.*.tif')
                img_paths = img_dir.get_all_files(img_name)
                img = File(img_paths[0])
                well_name = img.get_name('U\d\d--V\d\d')
                field_name = img.get_name('X\d\d--Y\d\d')
                channel = img.get_name('C\d\d')
                field_path = img.get_dir()
                well_path = Directory(field_path).get_dir()
                if (well_name == std_well and stage2before):
                    print('Stage2')
                    time.sleep(3)
                    if stage2_40x_before:
                        # Add 40x gain scan in std well to CAM list.
                        sock.send(stage2_40x)
                        cstart = camstart_com(af_job_40x, afr_40x, afs_40x)
                    if stage2_63x_before:
                        # Add 63x gain scan in std well to CAM list.
                        sock.send(stage2_63x)
                        cstart = camstart_com(af_job_63x, afr_63x, afs_63x)
                    # Start CAM scan.
                    sock.send(cstart)
                    stage2before = False
                if field_name == last_field and channel == 'C31':
                    if 'CAM' in well_path:
                        stage2after = True
                        if well_name == std_well:
                            sec_std_path = well_path
                    if ((well_name == last_well) and
                        ('CAM' not in well_path)):
                        stage1after = True
                    if stage1after and stage2after:
                        stage0 = False
                        print(stop_com)
                        sock.send(stop_com)
                        time.sleep(5)
                    if coord_file and 'CAM' not in well_path:
                        make_projs = False
                    else:
                        make_projs = True
                    ptime = time.time()
                    if make_projs:
                        print('Making max projections and '
                              'calculating histograms')
                        get_imgs(well_path, well_path, 'E00', img_save=False)
                        print(str(time.time()-ptime)+' secs')
                        begin = time.time()
            # get all CSVs and wells
            if coord_file:
                search = img_dir
            else:
                search = Directory(well_path)
            csvs = sorted(search.get_all_files('*.ome.csv'))
            for csv_path in csvs:
                csv_file = File(csv_path)
                # Get the filebase from the csv path.
                fbase = csv_file.cut_path('C\d\d.+$')
                #  Get the well from the csv path.
                well_name = csv_file.get_name('U\d\d--V\d\d')
                parent_path = csv_file.get_dir()
                well_path = Directory(parent_path).get_dir()
                if 'CAM' not in csv_path:
                    filebases.append(fbase)
                    fin_wells.append(well_name)
                    if std_well == well_name:
                        first_std_fbs.append(fbase)
                elif well_path == sec_std_path:
                    sec_std_fbs.append(fbase)
        except IndexError as e:
            print('No images yet... but maybe later?' , e)

        # For all experiment wells imaged so far, run R script
        if filebases and first_std_fbs and sec_std_fbs:
            # Get a unique set of filebases from the csv paths.
            filebases = sorted(set(filebases))
            first_std_fbs = sorted(set(first_std_fbs))
            sec_std_fbs = sorted(set(sec_std_fbs))
            # Get a unique set of names of the experiment wells.
            fin_wells = sorted(set(fin_wells))
            for fbase, well in zip(filebases, fin_wells):
                print(well)
                try:
                    print('Starting R...')
                    r_output = subprocess.check_output(['Rscript',
                                                        first_r_script,
                                                        imaging_dir,
                                                        fbase,
                                                        first_initialgains_file
                                                        ])
                    first_gain_dict = process_output(well,
                                                      r_output,
                                                      first_gain_dict
                                                      )
                    input_gains = r_output
                    r_output = subprocess.check_output(['Rscript',
                                                        sec_r_script,
                                                        imaging_dir,
                                                        first_std_fbs[0],
                                                        first_initialgains_file,
                                                        input_gains,
                                                        imaging_dir,
                                                        sec_std_fbs[0],
                                                        sec_initialgains_file
                                                        ])
                except OSError as e:
                    print('Execution failed:', e)
                    sys.exit()
                except subprocess.CalledProcessError as e:
                    print('Subprocess returned a non-zero exit status:', e)
                    sys.exit()
                print(r_output)
                sec_gain_dict = process_output(well, r_output, sec_gain_dict)
            # empty lists for keeping csv file base path names
            # and corresponding well names
            filebases = []
            fin_wells = []

    if not sec_gain_file:
        header = ['well', 'green', 'blue', 'yellow', 'red']
        csv_files = ['first_output_gains.csv', 'sec_output_gains.csv']
        for name, d in zip(csv_files, [first_gain_dict, sec_gain_dict]):
            csv_dicts = []
            for k, v in d.iteritems():
                csv_dicts.append({header[0]: k,
                                  header[1]: v[0],
                                  header[2]: v[1],
                                  header[3]: v[2],
                                  header[4]: v[3]
                                  })
            write_csv(os.path.normpath(working_dir+'/'+name), csv_dicts, header)

    if sec_gain_file:
        sec_gain_dict = read_csv(sec_gain_file,
                                 'well',
                                 ['green', 'blue', 'yellow', 'red'],
                                 sec_gain_dict
                                 )

    # Lists for storing command strings.
    com_list = []
    end_com_list = []
    com = '/cli:1 /app:matrix /cmd:deletelist\n'
    end_com = ['/cli:1 /app:matrix /cmd:deletelist\n']

    odd_even = 0
    dx = 0
    dy = 0
    pattern = -1
    start_of_part = False
    prev_well = ''

    wells = defaultdict()
    green_sorted = defaultdict(list)
    medians = defaultdict(int)

    for i, c in enumerate(['green', 'blue', 'yellow', 'red']):
        mlist = []
        for k, v in sec_gain_dict.iteritems():
            # Sort gain data into a list dict with well as key and where the
            # value is a list with a gain value for each channel.
            if c == 'green':
                # Round gain values to multiples of 10 in green channel
                green_val = int(round(int(v[i]), -1))
                green_sorted[green_val].append(k)
                well_no = 8*(int(get_wfx(k))-1)+int(get_wfy(k))
                wells[well_no] = k
            else:
                # Find the median value of all gains in
                # blue, yellow and red channels.
                mlist.append(int(v[i]))
                medians[c] = int(np.median(mlist))
    wells = OrderedDict(sorted(wells.items(), key=lambda t: t[0]))

    if stage3:
        print('Stage3')
        cstart = camstart_com(af_job_40x, afr_40x, afs_40x)
        stage_dict = green_sorted
        job_list = job_40x
        pattern = 0
        pattern_list = pattern_40x
        enable = 'true'
        fov_is = True
    if stage4:
        print('Stage4')
        cstart = camstart_com(af_job_63x, afr_63x, afs_63x)
        channels = range(4)
        stage_dict = wells
        old_well_no = wells.items()[0][0]-1
        job_list = job_63x
        fov_is = False
    for k, v in stage_dict.iteritems():
        if stage3:
            channels = [k,
                        medians['blue'],
                        medians['yellow'],
                        medians['red']
                        ]
        if stage4:
            # Check if well no 1-4 or 5-8 etc and continuous.
            if round((float(k)+1)/4) % 2 == odd_even:
                pattern = 0
                start_of_part = True
                if odd_even == 0:
                    odd_even = 1
                else:
                    odd_even = 0
            elif old_well_no + 1 != k:
                pattern = 0
                start_of_part = True
            else:
                pattern += 1
                start_of_part = False
            pattern_list = pattern_63x[pattern]
            old_well_no = k
        if start_of_part and fov_is:
            # Store the commands in lists, after one well at least.
            com_list.append(com)
            end_com_list.append(end_com)
            com = '/cli:1 /app:matrix /cmd:deletelist\n'
            fov_is = False
        elif start_of_part and not fov_is:
            # reset the com string
            com = '/cli:1 /app:matrix /cmd:deletelist\n'
            fov_is = False
        for i, c in enumerate(channels):
            if stage3:
                set_gain = str(c)
                start_of_part = True
            if stage4:
                set_gain = str(sec_gain_dict[v][i])
            if i < 2:
                detector = '1'
                job = job_list[i + 3*pattern]
            if i >= 2:
                detector = '2'
                job = job_list[i - 1 + 3*pattern]
            com = com + gain_com(job, detector, set_gain) + '\n'
        for well in v:
            if stage4:
                well = v
            if well != prev_well:
                prev_well = well
                for i in range(2):
                    for j in range(2):
                        if stage4:
                            # Only enable selected wells from file (arg)
                            fov = '{}--X0{}--Y0{}'.format(well, j, i)
                            if fov in coords.keys():
                                enable = 'true'
                                dx = coords[fov][0]
                                dy = coords[fov][1]
                                fov_is = True
                            else:
                                enable = 'false'
                        if enable == 'true' or stage3:
                            com = (com +
                                   enable_com(well,
                                              'X0{}--Y0{}'.format(j, i),
                                              enable
                                              )+
                                   '\n'+
                                   # dx dy switched, scan rot -90 degrees
                                   cam_com(pattern_list,
                                           well,
                                           'X0{}--Y0{}'.format(j, i),
                                           str(dy),
                                           str(dx)
                                           )+
                                   '\n')
                            end_com = ['CAM',
                                       well,
                                       'E03',
                                       'X0{}--Y0{}'.format(j, i)
                                       ]
    if fov_is:
        # Store the last unstored commands in lists, after one well at least.
        com_list.append(com)
        end_com_list.append(end_com)

    for com, end_com in zip(com_list, end_com_list):
        # Send gain change command to server in the four channels.
        # Send CAM list to server.
        print(com)
        sock.send(com)
        time.sleep(3)
        # Start scan.
        print(start_com)
        sock.send(start_com)
        time.sleep(3)
        # Start CAM scan.
        print(cstart)
        sock.send(cstart)
        time.sleep(3)
        if stage3:
            sock.recv_timeout(40, end_com)
        if stage4:
            stage5 = True
        while stage5:
            reply = sock.recv_timeout(120, ['image--'])
            # parse reply, check well (UV), job-order (E), field (XY),
            # z slice (Z) and channel (C). Get field path.
            # Get all image paths in field. Rename images.
            # Make a max proj per channel and field.
            # Save meta data and image max proj.
            if 'image' in reply:
                img_name = File(reply).get_name('image--.*.tif')
                print(img_name)
                job_order = File(reply).get_name('E\d\d')
                img_paths = img_dir.get_all_files(img_name)
                try:
                    field_path = File(img_paths[0]).get_dir()
                    get_imgs(field_path, imaging_dir, job_order, csv_save=False)
                except IndexError as e:
                    print('No images yet... but maybe later?' , e)
            if all(test in reply for test in end_com):
                stage5 = False
        #time.sleep(3)
        # Stop scan
        print(stop_cam_com)
        sock.send(stop_cam_com)
        time.sleep(3)
        print(stop_com)
        sock.send(stop_com)
        time.sleep(5)

    print('\nExperiment finished!')

if __name__ =='__main__':
    main(sys.argv[1:])
