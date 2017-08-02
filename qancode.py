import cv2
import getpass
import json
import tempfile
import time
import numpy as np
import os
import pandas as pd
import re
import requests
import subprocess
import sys
import urllib
import uuid

from abc import ABCMeta, abstractmethod
from collections import defaultdict
from io import BytesIO
from itertools import chain
from PIL import Image
from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from selenium.webdriver.common.by import By
from tqdm import tqdm


"""
Purpose
-------
Provide robust framework for performing browser tasks with Selenium.

New data gathering tasks can inherit from the SeleniumTask class.

New data comparison tasks between production data and RC data can inherit
from the URLComparison class.

New data comparison tasks between browsers for the same URL can inherit
from the BrowserComparison class.

The DataManager class launches DataWorkers to complete individual tasks
in a fault-tolerant way.

The QANCODE object organizes data gathering tasks and data comparison
tasks into a complete pipeline that can be called with a single
method, e.g. QANCODE.compare_facets().


Example
-------
# Run qancode in interactive Python session.
$ python -i qancode.py

# Initiate QANCODE object with URL to compare to production.
>>> qa = QANCODE(rc_url='https://test.encodedcc.org')

First:

# Run facet comparison for Experiment items in Safari as public and
# admin user.
>>> qa.compare_facets(users=['Public', 'encxxxtest@gmail.com'],
                      browsers=['Safari'],
                      item_types=['/search/?type=Experiment'])

Will return comparison of data between production and RC for a given browser
as well as comparison of data between browsers for a given URL.

Second:

# Find the difference between two screenshots.
>>> qa.find_differences(browsers=['Safari'],
                        users=['Public'],
                        item_types=['/biosamples/ENCBS632MTU/'])

Will output image showing difference if found.

# Perform action before taking screenshot.
>>> qa.find_differences(browsers=['Chrome'],
                        users=['Public'],
                        action_tuples=[('/experiments/ENCSR985KAT/', OpenUCSCGenomeBrowserHG19)])

Will open UCSC Genome Browser for hg19 assembly from Experiment page and then
take screenshot to compare.

# Equivalently can pass item_type and click_path instead of action_tuple:
>>> qa.find_differences(browsers=['Chrome'],
                        users=['Public'],
                        item_types=['/experiments/ENCSR985KAT/'],
                        click_paths=[OpenUCSCGenomeBrowserHG19])

Required
--------
Selenium webdriver for Chrome, Firefox.

Safari Technology Preview version.

OpenCV and PIL for Python 3.

To run as any user != Public must create ~/qa_credentials.json file with
list of objects containing username and password fields:

[{"username": "enxxxxtest@gmail.com", "password": "xxxxx"},
 {"username": "encxxxxtest2@gmail.com", "password": "xxxxx"},
 {"username": "encxxxxtest4@gmail.com", "password": "xxxxx"}]

"""

# Default browsers.
BROWSERS = ['Chrome',
            'Firefox',
            'Safari']

# Default users.
USERS = ['Public',
         'encoded.test@gmail.com',
         'encoded.test2@gmail.com',
         'encoded.test4@gmail.com']


class bcolors:
    """
    Helper class for text color definitions.
    """
    OKBLUE = '\x1b[36m'
    OKGREEN = '\x1b[1;32m'
    WARNING = '\x1b[33m'
    FAIL = '\x1b[31m'
    ENDC = '\x1b[0m'


#######################
# Page object models. #
#######################


class FrontPage(object):
    """
    Page object models allow selectors to be defined in one place and then
    used by all of the test.
    """
    login_button_text = 'Submitter sign-in'
    logout_button_text = 'Submitter sign out'
    menu_button_data_css = '#main > ul > li:nth-child(1) > a'
    menu_button_data_alt_css = '#main > ul > li:nth-child(1) > button'
    drop_down_search_button_css = '#main > ul > li.dropdown.open > ul > li:nth-child(2) > a'


class SignInModal(object):
    """
    Page object model.
    """
    login_modal_class = 'auth0-lock-header-logo'
    google_button_css = '#auth0-lock-container-1 > div > div.auth0-lock-center > form > div > div > div:nth-child(3) > span > div > div > div > div > div > div > div > div > div > div.auth0-lock-social-buttons-container > button:nth-child(2) > div.auth0-lock-social-button-icon'
    button_tag = 'button'
    user_id_input_css = '#identifierId'
    user_next_button_css = '#identifierNext > content > span'
    password_input_css = '#password > div.aCsJod.oJeWuf > div > div.Xb9hP > input'
    password_next_button_css = '#passwordNext > content > span'
    two_step_user_id_input_css = '#username'
    two_step_password_input_css = '#password'
    two_step_submit_css = '#login > input'
    two_step_send_sms_css = '#sms-send > input.submit-button'
    two_step_code_input_css = '#otp'
    two_step_submit_verification_css = '#otp-box > div > input.go-button'


class SearchPageList(object):
    """
    Page object model.
    """
    facet_box_class = 'facets'
    see_more_buttons_css = '#content > div > div > div > div > div.col-sm-5.col-md-4.col-lg-3 > div > div > div > ul > div.pull-right > small > button'
    facet_class = 'facet'
    category_title_class = 'facet-item'
    number_class = 'pull-right'
    download_metadata_button_xpath = '//*[contains(text(), "Download")]'


class SearchPageMatrix(object):
    """
    Page object model.
    """
    see_more_top_buttons_css = '#content > div > div > div > div.col-sm-7.col-md-8.col-lg-9.sm-no-padding > div > div > div > ul > div.pull-right > small > button'
    see_more_left_buttons_css = '#content > div > div > div > div.col-sm-5.col-md-4.col-lg-3.sm-no-padding > div > div > div > ul > div.pull-right > small > button'
    box_top_css = '#content > div > div > div:nth-child(1) > div.col-sm-7.col-md-8.col-lg-9.sm-no-padding > div'
    box_left_css = '#content > div > div > div:nth-child(2) > div.col-sm-5.col-md-4.col-lg-3.sm-no-padding > div'
    facets_top_class = 'facet'
    facets_left_class = 'facet'


class ExperimentPage(object):
    """
    Page object model.
    """
    done_panel_class = 'done'
    title_tag_name = 'h4'
    graph_close_button_css = 'div > div:nth-child(2) > div.file-gallery-graph-header.collapsing-title > button'
    sort_by_accession_xpath = '//div/div[3]/div[2]/div/table[2]/thead/tr[2]/th[1]'
    all_buttons_tag_name = 'button'
    download_graph_png_button_xpath = '//*[contains(text(), "Download Graph")]'
    file_type_column_xpath = '//div[@class="file-gallery-counts"]//..//table[@class="table table-sortable"]//tr//td[2]'
    accession_column_relative_xpath = '..//td[1]//span//div//span//a'
    information_button_relative_xpath = '..//td[1]//span//button//i'
    file_graph_tab_xpath = '//div[@class="tab-nav"]//li[2]'


class FilePage(object):
    """
    Page object model.
    """
    download_button_xpath = '//*[contains(text(), "Download")]'


class AntibodyPage(object):
    """
    Page object model.
    """
    expanded_document_panels_xpath = '//div[@class="document__detail active"]//a[@href]'


class ReportPage(object):
    """
    Page object model.
    """
    download_tsv_report_button_xpath = '//*[contains(text(), "Download TSV")]'


class VisualizeModal(object):
    """
    Page object model.
    """
    modal_class = 'modal-content'
    UCSC_link_partial_link_text = 'UCSC'


class DownloadModal(object):
    """
    Page object model.
    """
    download_button_xpath = '/html/body/div[2]/div/div/div[1]/div/div/div[3]/div/a[2]'


class InformationModal(object):
    """
    Page object model.
    """
    download_icon_xpath = '/html/body/div[2]/div/div/div[1]/div/div/div[2]/div/dl/div[8]/dd/span/div/span/a/i'


class NavBar(object):
    """
    Page object model.
    """
    testing_warning_banner_button_css = '#navbar > div.test-warning > div > p > button'


class LoadingSpinner(object):
    """
    Page object model.
    """
    loading_spinner_class = 'loading-spinner'


class DocumentPreview(object):
    """
    Page object model.
    """
    document_expand_buttons_class = 'document__file-detail-switch'
    document_files_xpath = '//div[@class="document__file"]//a[@href]'


class UCSCGenomeBrowser(object):
    """
    Page object model.
    """
    zoom_one_id = 'hgt.in1'

##################################################################
# Abstract methods for data gathering and data comparison tasks. #
##################################################################


class SeleniumTask(metaclass=ABCMeta):
    """
    ABC for defining a Selenium task.
    """

    def __init__(self, driver, item_type, click_path, server_name=None, **kwargs):
        self.driver = driver
        self.item_type = item_type
        self.click_path = click_path
        self.server_name = server_name
        self.temp_dir = kwargs.get('temp_dir', None)
        self.kwargs = kwargs

    def _wait_for_loading_spinner(self):
        if any([y.is_displayed() for y in self.driver.find_elements_by_class_name(LoadingSpinner.loading_spinner_class)]):
            print('Waiting for spinner')
            browser = self.driver.capabilities['browserName'].title()
            for tries in tqdm(range(10)):
                if any([y.is_displayed() for y in self.driver.find_elements_by_class_name(LoadingSpinner.loading_spinner_class)]):
                    time.sleep(1)
                else:
                    print('Loading complete')
                    break
            else:
                print('{} WARNING: Loading spinner still visible'
                      ' on {} in {} after ten seconds.{}'.format(bcolors.FAIL,
                                                                 self.driver.current_url,
                                                                 browser,
                                                                 bcolors.ENDC))
        else:
            print('Loading complete')

    def _try_load_item_type(self):
        time.sleep(2)
        if ((self.item_type is not None)
                and (self.item_type != '/')):
            type_url = self.driver.current_url + self.item_type
            print('Getting type: {}'.format(self.item_type))
            self.driver.get(type_url)
        time.sleep(2)
        self._wait_for_loading_spinner()
        self.driver.wait.until(
            EC.element_to_be_clickable((By.ID, 'navbar')))

    def _try_perform_click_path(self):
        if self.click_path is not None:
            print('Performing click path: {}'.format(self.click_path.__name__))
            return self.click_path(self.driver)

    def _expand_document_details(self):
        expand_buttons = self.driver.wait.until(EC.presence_of_all_elements_located(
            (By.CLASS_NAME, DocumentPreview.document_expand_buttons_class)))
        for button in expand_buttons:
            try:
                button.click()
            except:
                pass

    def _get_rid_of_test_warning_banner(self):
        testing_warning_banner_button = WebDriverWait(self.driver, 3).until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, NavBar.testing_warning_banner_button_css)))
        testing_warning_banner_button.click()

    @abstractmethod
    def get_data(self):
        pass


class BrowserComparison(metaclass=ABCMeta):
    """
    ABC for comparing data between browsers.
    """

    def __init__(self, user, url, item_type, browsers, all_data):
        self.all_data = all_data
        self.user = user
        self.url = url
        self.item_type = item_type
        self.browsers = browsers
        self.url_data = [d for d in all_data if ((d['user'] == user)
                                                 and (d['item_type'] == item_type)
                                                 and (d['url'] == url))]

    @abstractmethod
    def compare_data(self):
        pass


class URLComparison(metaclass=ABCMeta):
    """
    ABC for comparing data between prod and RC given browser and user.
    """

    def __init__(self, browser, user, prod_url, rc_url, item_type, all_data, click_path=None):
        self.browser = browser
        self.user = user
        self.all_data = all_data
        self.prod_url = prod_url
        self.rc_url = rc_url
        self.item_type = item_type
        self.click_path = click_path
        self.prod_data = [d['data'] for d in all_data
                          if ((d['url'] == prod_url)
                              and (d['user'] == user)
                              and (d['browser'] == browser)
                              and (d['item_type'] == item_type)
                              and (d['click_path'] == click_path))]
        self.rc_data = [d['data'] for d in all_data
                        if ((d['url'] == rc_url)
                            and (d['user'] == user)
                            and (d['browser'] == browser)
                            and (d['item_type'] == item_type)
                            and (d['click_path'] == click_path))]
        assert len(self.prod_data) == len(self.rc_data)

    @abstractmethod
    def compare_data(self):
        pass

#########################################
# Selenium setup and sign-in procedures. #
#########################################


class NewDriver(object):
    """
    Initiate new Selenium driver.
    """

    def __init__(self, browser, url):
        print('Opening {} in {}'.format(url, browser))
        if browser == 'Safari':
            self.driver = webdriver.Safari(
                port=0, executable_path='/Applications/Safari Technology Preview.app/Contents/MacOS/safaridriver')
        elif browser == 'Firefox':
            # Allow automatic downloading of specified MIME types.
            mime_types = 'binary/octet-stream,application/x-gzip,application/gzip,application/pdf,text/plain,text/tsv,image/png,image/jpeg'
            fp = webdriver.FirefoxProfile()
            fp.set_preference(
                'browser.download.manager.showWhenStarting', False)
            fp.set_preference(
                'browser.helperApps.neverAsk.saveToDisk', mime_types)
            fp.set_preference(
                'plugin.disable_full_page_plugin_for_types', mime_types)
            fp.set_preference('pdfjs.disabled', True)
            self.driver = webdriver.Firefox(firefox_profile=fp)
        else:
            self.driver = getattr(webdriver, browser)()
        self.driver.wait = WebDriverWait(self.driver, 5)
        self.driver.wait_long = WebDriverWait(self.driver, 15)
        self.driver.set_window_size(1500, 950)
        self.driver.set_window_position(0, 0)
        self.driver.get(url)

    def driver(self):
        return self.driver


class SignIn(object):
    """
    Run through OAuth authentication procedure.
    """

    def __init__(self, driver, user, cred_file=os.path.expanduser('~/qa_credentials.json')):
        self.driver = driver
        self.user = user
        self.user_credentials = self.open_credential_file(cred_file)
        self.creds = self.get_credentials_of_user()
        self.sign_in()

    @staticmethod
    def open_credential_file(cred_file):
        with open(cred_file) as f:
            return json.load(f)

    def get_credentials_of_user(self):
        creds = [c for c in self.user_credentials if c['username'] == self.user]
        if len(creds) == 0 and self.user != 'Public':
            raise ValueError('Unknown user')
        else:
            return creds

    def wait_for_modal_to_quit(self):
        wait_time = 10
        while wait_time > 0:
            try:
                WebDriverWait(self.driver, 1).until(EC.presence_of_element_located(
                    (By.CLASS_NAME, SignInModal.login_modal_class)))
                time.sleep(1)
                wait_time -= 1
            except TimeoutException:
                break
        if wait_time < 0:
            raise TimeoutException

    def is_two_step(self):
        if 'stanford' in self.driver.current_url:
            return True
        else:
            return False

    def signed_in(self):
        try:
            self.driver.wait.until(EC.presence_of_element_located(
                (By.LINK_TEXT, FrontPage.logout_button_text)))
            print('Login successful')
            time.sleep(3)
            return True
        except TimeoutError:
            return False

    def login_two_step(self):
        user_id = self.driver.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SignInModal.two_step_user_id_input_css)))
        user_id.send_keys(self.creds[0]['username'])
        password = self.driver.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SignInModal.two_step_password_input_css)))
        pw = getpass.getpass()
        password.send_keys(pw)
        pw = None
        submit = self.driver.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, SignInModal.two_step_submit_css)))
        submit.click()
        send_sms = self.driver.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, SignInModal.two_step_send_sms_css)))
        send_sms.click()
        code = self.driver.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SignInModal.two_step_code_input_css)))
        verification = input('Authentication code: ')
        code.send_keys(verification)
        submit = self.driver.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, SignInModal.two_step_submit_verification_css)))
        submit.click()

    def sign_in(self):
        print('Logging in as {}'.format(self.user))
        original_window_handle = self.driver.window_handles[0]
        self.driver.switch_to_window(original_window_handle)
        login_button = self.driver.wait.until(EC.element_to_be_clickable(
            (By.PARTIAL_LINK_TEXT, FrontPage.login_button_text)))
        try:
            login_button.click()
            self.driver.wait.until(EC.presence_of_element_located(
                (By.CLASS_NAME, SignInModal.login_modal_class)))
        except TimeoutException:
            login_button = self.driver.wait.until(EC.element_to_be_clickable(
                (By.PARTIAL_LINK_TEXT, FrontPage.login_button_text)))
            login_button.click()
        try:
            time.sleep(1)
            google_button = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, SignInModal.google_button_css)))
            google_button.click()
        except TimeoutException:
            # Hack to find button in Safari.
            for button in self.driver.find_elements_by_tag_name(SignInModal.button_tag):
                if '@' in button.text:
                    button.click()
                    break
            self.wait_for_modal_to_quit()
            return None
        try:
            user_id = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, SignInModal.user_id_input_css)))
        except TimeoutException:
            new_window_handle = [h for h in self.driver.window_handles
                                 if h != original_window_handle][0]
            self.driver.switch_to_window(new_window_handle)
            user_id = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, SignInModal.user_id_input_css)))
        user_id.send_keys(self.creds[0]['username'])
        next_button = self.driver.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, SignInModal.user_next_button_css)))
        next_button.click()
        try:
            pw = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, SignInModal.password_input_css)))
            pw.send_keys(self.creds[0]['password'])
            next_button = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, SignInModal.password_next_button_css)))
            time.sleep(0.5)
            next_button.click()
            time.sleep(0.5)
        except TimeoutException:
            if self.is_two_step():
                self.login_two_step()
            else:
                new_window_handle = [h for h in self.driver.window_handles
                                     if h != original_window_handle][0]
                self.driver.switch_to_window(new_window_handle)
                next_button = self.driver.wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, SignInModal.password_next_button_css)))
                next_button.click()
        self.driver.switch_to_window(original_window_handle)
        return self.signed_in()


###################
# Selenium tasks. #
###################


class GetFacetNumbers(SeleniumTask):
    """
    Implementation of Task for getting facet number data.
    """

    def matrix_page(self):
        print('Matrix page detected')
        box_top = self.driver.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, SearchPageMatrix.box_top_css)))
        box_left = self.driver.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, SearchPageMatrix.box_left_css)))
        see_more_top_buttons = self.driver.find_elements_by_css_selector(
            SearchPageMatrix.see_more_top_buttons_css)
        see_more_left_buttons = self.driver.find_elements_by_css_selector(
            SearchPageMatrix.see_more_left_buttons_css)
        for button in chain(see_more_top_buttons, see_more_left_buttons):
            button.click()
        facets_top = box_top.find_elements_by_class_name(
            SearchPageMatrix.facets_top_class)
        facets_left = box_left.find_elements_by_class_name(
            SearchPageMatrix.facets_left_class)
        facets = chain(facets_top, facets_left)
        return facets

    def search_page(self):
        print('Search page detected')
        facet_box = self.driver.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, SearchPageList.facet_box_class)))
        see_more_buttons = facet_box.find_elements_by_css_selector(
            SearchPageList.see_more_buttons_css)
        for button in see_more_buttons:
            button.click()
        facets = self.driver.find_elements_by_class_name(
            SearchPageList.facet_class)
        return facets

    def get_data(self):
        if self.item_type is None:
            try:
                data_button = self.driver.wait_long.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, FrontPage.menu_button_data_css)))
            except TimeoutException:
                data_button = self.driver.wait_long.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, FrontPage.menu_button_data_alt_css)))
            data_button.click()
            search_button = self.driver.wait_long.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, FrontPage.drop_down_search_button_css)))
            search_button.click()
        else:
            type_url = self.driver.current_url + self.item_type
            print('Getting type: {}'.format(self.item_type))
            self.driver.get(type_url)
        try:
            self.driver.wait.until(EC.title_contains('Search'))
        except TimeoutException:
            pass
        if 'matrix' in self.driver.current_url:
            facets = self.matrix_page()
        else:
            facets = self.search_page()
        data_dict = defaultdict(list)
        for facet in facets:
            title = facet.find_element_by_css_selector(
                'h5').text.replace(':', '').strip()
            categories = [
                c.text for c in facet.find_elements_by_class_name(SearchPageList.category_title_class)]
            print('Collecting values in {}.'.format(title))
            numbers = [n.text for n in facet.find_elements_by_class_name(
                SearchPageList.number_class) if n.text != '']
            assert len(categories) == len(numbers)
            if title in data_dict.keys():
                title_number = len([t for t in data_dict.keys()
                                    if t.startswith(title)]) + 1
                title = title + str(title_number)
            data_dict[title] = list(zip(categories, numbers))
        return data_dict


class GetScreenShot(SeleniumTask):
    """
    Get screenshot for comparison.
    """

    def stitch_image(self, image_path):
        print('Stitching screenshot')
        self.driver.execute_script('window.scrollTo(0, {});'.format(0))
        client_height = self.driver.execute_script(
            'return document.documentElement.clientHeight;')
        scroll_height = self.driver.execute_script(
            'return document.body.scrollHeight;')
        image_slices = []
        while True:
            scroll_top = self.driver.execute_script(
                'return document.body.scrollTop || document.documentElement.scrollTop;')
            time.sleep(1)
            image = Image.open(
                BytesIO(self.driver.get_screenshot_as_png())).convert('RGB')
            if ((((2 * client_height) + scroll_top) >= scroll_height)
                    and (scroll_height != (client_height + scroll_top))):
                # Get difference for cropping next image.
                difference_to_keep = abs(
                    2 * (scroll_height - (client_height + scroll_top)))
            if np.allclose(scroll_height, (client_height + scroll_top), rtol=0.0025):
                image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
                y_bound_low = image.shape[0] - difference_to_keep
                image = image[y_bound_low:, :]
                image_slices.append(image)
                break
            image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            image_slices.append(image)
            self.driver.execute_script(
                'window.scrollTo(0, {});'.format(client_height + scroll_top))
            try:
                self.driver.execute_script(
                    'document.getElementById("navbar").style.visibility = "hidden";')
            except:
                pass
        stitched = np.concatenate(*[image_slices], axis=0)
        # Crop stitched rightside a bit so scrollbar doesn't influence diff.
        stitched = stitched[:, :stitched.shape[1] - 20]
        cv2.imwrite(image_path, stitched)

    def take_screenshot(self):
        current_url = self.driver.current_url
        print('Taking picture of {}'.format(current_url))
        filename = '{}{}.png'.format(self.server_name, uuid.uuid4().int)
        image_path = os.path.join(self.temp_dir, filename)
        print(image_path)
        client_height = self.driver.execute_script(
            'return document.documentElement.clientHeight;')
        scroll_height = self.driver.execute_script(
            'return document.body.scrollHeight;')
        if ((self.driver.capabilities['browserName'] == 'safari')
                or (client_height == scroll_height)):
            self.driver.save_screenshot(image_path)
        else:
            self.stitch_image(image_path)
        return image_path

    def make_experiment_pages_look_the_same(self):
        for y in self.driver.wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, ExperimentPage.done_panel_class))):
            try:
                title = y.find_element_by_tag_name(
                    ExperimentPage.title_tag_name).text
                if title == 'Files':
                    graph_close_button = WebDriverWait(y, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ExperimentPage.graph_close_button_css)))
                    graph_close_button.click()
                    y.find_element_by_xpath(
                        ExperimentPage.sort_by_accession_xpath).click()
            except:
                pass
            if self.click_path != DownloadGraphFromExperimentPage:
                try:
                    self.driver.find_elements_by_xpath(
                        ExperimentPage.file_graph_tab_xpath)[0].click()
                except:
                    pass

    def get_data(self):
        self._try_load_item_type()
        self._try_perform_click_path()
        if 'experiment' in self.driver.current_url:
            try:
                self.make_experiment_pages_look_the_same()
            except:
                pass
        try:
            self._expand_document_details()
        except:
            pass
        try:
            self._get_rid_of_test_warning_banner()
        except:
            pass
        self.driver.execute_script(
            'window.scrollTo(0,document.body.scrollHeight);')
        time.sleep(1)
        self.driver.execute_script('window.scrollTo(0, 0);')
        time.sleep(1)
        image_path = self.take_screenshot()
        return image_path


class DownloadFiles(SeleniumTask):
    """
    Download file given click_path.
    """

    def _get_metadata_from_files_txt(self):
        download_directory = os.path.join(os.path.expanduser('~'), 'Downloads')
        file_path = os.path.join(download_directory, 'files.txt')
        with open(file_path, 'r') as f:
            meta_data_link = f.readline().strip()
            accessions = [f.split('/files/')[1].split('/')[0]
                          for f in f.readlines()]
        # Get metadata.tsv.
        print('Detected {} accessions'.format(len(accessions)))
        print('Getting metadata.tsv from {}'.format(meta_data_link))
        # Workaround for Safari.
        if self.driver.capabilities['browserName'] == 'safari':
            r = urllib.request.urlopen(meta_data_link)
            data = r.read()
            metadata = pd.read_table(BytesIO(data))
        else:
            self.driver.execute_script(
                'window.open("{}");'.format(meta_data_link))
            time.sleep(5)
            metadata_path = os.path.join(download_directory, 'metadata.tsv')
            metadata = pd.read_table(metadata_path)
        if set(accessions) == set(metadata['File accession']):
            print('{}Accessions match: files.txt and metadata.tsv{}'.format(
                bcolors.OKBLUE, bcolors.ENDC))
        else:
            print('{}WARNING: Accession mismatch between files.txt and metadata.tsv{}'.format(
                bcolors.FAIL, bcolors.ENDC))
            print('{}{}{}'.format(bcolors.FAIL, set(accessions).symmetric_difference(
                set(metadata['File accession'])), bcolors.ENDC))
        if self.kwargs.get('delete'):
            try:
                os.remove(metadata_path)
            except:
                pass

    def _check_download_folder(self, filename, download_start_time, results):
        files = os.listdir(os.path.join(
            os.path.expanduser('~'), 'Downloads'))
        for file in files:
            full_path = os.path.join(
                os.path.expanduser('~'), 'Downloads', file)
            # Inexact match to deal with multiple download of same file.
            # Safari overwrites multiple downloads of same file so filepath
            # not unique.
            if ((file.startswith(filename[:len(filename) - 8]))
                    and ((self.driver.capabilities['browserName'] == 'safari')
                         or (file not in [r[3] for r in results]))):
                return (True, full_path, filename, file)
        return (False, full_path, filename, None)

    def _wait_for_download_to_finish(self):
        # Wait for download completion.
        print('Waiting for download to finish')
        while True:
            files = os.listdir(os.path.join(
                os.path.expanduser('~'), 'Downloads'))
            # Check for downloading files from different browsers.
            if (any([('.part' in f) for f in files])
                    or any([('.download' in f) for f in files])
                    or any([('.crdownload' in f) for f in files])):
                time.sleep(5)
            else:
                break

    def _find_downloaded_file(self):
        """
        Checks for downloaded file in Downloads directory.
        """
        time.sleep(2)
        results = []
        self._wait_for_download_to_finish()
        for filename, download_start_time in zip(self.filenames, self.download_start_times):
            results.append(self._check_download_folder(
                filename, download_start_time, results))
        # Clean up.
        for result in results:
            print('Checking for downloaded file {}'.format(result[2]))
            if result[0]:
                print('{}DOWNLOAD SUCCESS: {}{}'.format(
                    bcolors.OKBLUE, result[2], bcolors.ENDC))
                if ((result[2] == 'files.txt')
                        and (self.click_path == DownloadMetaDataFromSearchPage)):
                    self._get_metadata_from_files_txt()
                if self.kwargs.get('delete'):
                    try:
                        os.remove(result[1])
                    except:
                        pass
            else:
                print('{}DOWNLOAD FAILURE: {}{}'.format(
                    bcolors.FAIL, result[2], bcolors.ENDC))

    def get_data(self):
        self._try_load_item_type()
        if self.click_path == DownloadDocumentsFromAntibodyPage:
            self._expand_document_details()
        cp = self._try_perform_click_path()
        self.filenames = cp.filenames
        self.download_start_times = cp.download_start_times
        self._find_downloaded_file()

##########################
# Data comparison tasks. #
##########################


class CompareFacetNumbersBetweenBrowsers(BrowserComparison):
    """
    Implementation of BrowserComparison for facet numbers.
    """

    def compare_data(self):
        """
        Return comparison of data between browsers given server (prod/RC),
        user, item_type.
        """
        print('Comparing data between browsers: {}.'.format(self.browsers))
        print('As user: {}'.format(self.user))
        print('URL: {}'.format(self.url))
        print('Item type: {}'.format(self.item_type))
        # Find keys that are not in all groups.
        all_keys = set.union(*[set(d['data'].keys()) for d in self.url_data])
        common_keys = set.intersection(*[set(d['data'].keys())
                                         for d in self.url_data])
        different_keys = all_keys - common_keys
        if different_keys:
            for key in different_keys:
                print(key)
                # Print groups that have key.
                browsers_with_key = set([d['browser'] for d in self.url_data
                                         if key in d['data'].keys()])
                if browsers_with_key:
                    print('{}{}In browsers: {}{}'.format(
                        ' ' * 5, bcolors.WARNING, list(browsers_with_key), bcolors.ENDC))
                # Print groups that do not have key.
                browsers_without_key = set(
                    [d['browser'] for d in self.url_data if key not in d['data'].keys()])
                if browsers_without_key:
                    print('{}{}Not in browsers: {}{}'.format(
                        ' ' * 5, bcolors.FAIL, list(browsers_without_key), bcolors.ENDC))
        if common_keys:
            for key in sorted(common_keys):
                print(key)
                category_data_by_browser = [(d['browser'], set(d['data'][key]))
                                            for d in self.url_data]
                all_data = set.union(*[d[1] for d in category_data_by_browser])
                common_data = set.intersection(*[d[1] for d
                                                 in category_data_by_browser])
                different_data = all_data - common_data
                if different_data:
                    for dd in different_data:
                        browsers_with_different_data = [
                            d[0] for d in category_data_by_browser if dd in d[1]]
                        print('{}{}{}{}'.format(
                            ' ' * 5, bcolors.OKGREEN, dd, bcolors.ENDC))
                        print('{}{}In browsers: {}{}'.format(
                            ' ' * 10, bcolors.WARNING, list(browsers_with_different_data), bcolors.ENDC))
                        browsers_without_different_data = [
                            d[0] for d in category_data_by_browser if dd not in d[1]]
                        print('{}{}Not in browsers: {}{}'.format(
                            ' ' * 10, bcolors.FAIL, list(browsers_without_different_data), bcolors.ENDC))
                else:
                    print('{}{}MATCH{}'.format(
                        ' ' * 5, bcolors.OKBLUE, bcolors.ENDC))


class CompareFacetNumbersBetweenURLS(URLComparison):
    """
    Implementation of URLComparison for facet numbers.
    """

    def compare_data(self):
        print('Comparing data between URLs.')
        print('As user: {}'.format(self.user))
        print('Browser: {}'.format(self.browser))
        print('First URL: {}'.format(self.prod_url))
        print('Second URL: {}'.format(self.rc_url))
        print('Item type: {}'.format(self.item_type))
        prod_data = self.prod_data[0]
        rc_data = self.rc_data[0]
        if prod_data.keys() != rc_data.keys():
            print('Different keys:')
            in_prod = prod_data.keys() - rc_data.keys()
            in_rc = rc_data.keys() - prod_data.keys()
            if in_prod:
                print('RC missing: {}'.format(in_prod))
            if in_rc:
                print('Production missing: {}'.format(in_rc))
        for title in sorted(set(prod_data.keys()).union(set(rc_data.keys()))):
            prod = set(prod_data[title])
            rc = set(rc_data[title])
            if prod != rc:
                in_prod = sorted(prod - rc)
                in_rc = sorted(rc - prod)
                print(title.upper())
                if ((len(in_prod) == len(in_rc))
                        and (set([k[0] for k in prod_data[title]]) == set([k[0] for k in rc_data[title]]))):
                    for p, r in zip(in_prod, in_rc):
                        print('{}{}{}: {} (prod), {} (rc){}'.format(
                            ' ' * 5, bcolors.FAIL, p[0], p[1], r[1], bcolors.ENDC))
                else:
                    both_keys = set([x[0] for x in in_prod]).intersection(
                        set([x[0] for x in in_rc]))
                    both_prod = sorted(
                        [x for x in in_prod if x[0] in both_keys])
                    both_rc = sorted([x for x in in_rc if x[0] in both_keys])
                    if both_prod:
                        for p, r in zip(both_prod, both_rc):
                            print('{}{}{}: {} (prod), {} (rc){}'.format(
                                ' ' * 5, bcolors.FAIL, p[0], p[1], r[1], bcolors.ENDC))
                    only_prod = [x for x in in_prod if x[0] not in both_keys]
                    if only_prod:
                        print('{}{}prod: {}{}'.format(
                            ' ' * 5, bcolors.WARNING, only_prod, bcolors.ENDC))
                    only_rc = [x for x in in_rc if x[0] not in both_keys]
                    if only_rc:
                        print('{}{}rc: {}{}'.format(
                            ' ' * 5, bcolors.WARNING, only_rc, bcolors.ENDC))
            else:
                print(title)
                print('{}{}MATCH{}'.format(' ' * 5, bcolors.OKBLUE, bcolors.ENDC))


class CompareScreenShots(URLComparison):
    def is_same(self, difference):
        self.diff_distance_metric = difference.sum()
        if np.any(difference):
            # Thresholded value.
            if difference.sum() > 50000:
                return False
        return True

    def pad_if_different_shape(self, image_one, image_two):
        image_one_row_number = image_one.shape[0]
        image_two_row_number = image_two.shape[0]
        pad_shape = abs(image_one_row_number - image_two_row_number)
        if image_one_row_number > image_two_row_number:
            image_two = np.pad(
                image_two, ((0, pad_shape), (0, 0), (0, 0)), mode='constant')
        else:
            image_one = np.pad(
                image_one, ((0, pad_shape), (0, 0), (0, 0)), mode='constant')
        return image_one, image_two

    def compute_image_difference(self):
        directory = os.path.join(
            os.path.expanduser('~'), 'Desktop', 'image_diff')
        if not self.item_type.endswith('/'):
            self.item_type = self.item_type + '/'
        if len(self.item_type) <= 1:
            sub_name = '_front_page_'
        else:
            sub_name = re.sub(
                '[/?=&+.%]', '_', self.item_type).replace('__', '_')
        user_name = self.user.split('@')[0].replace('.', '_').lower()
        if not os.path.exists(directory):
            print('Creating directory on Desktop')
            os.makedirs(directory)
        click_path = None if self.click_path is None else self.click_path.__name__
        path_name = '{}{}{}_{}_prod_rc_diff.png'.format(
            self.browser.lower(), sub_name.upper(), user_name, click_path)
        image_one = cv2.imread(self.prod_data[0])
        image_two = cv2.imread(self.rc_data[0])
        if image_one.shape[0] != image_two.shape[0]:
            image_one, image_two = self.pad_if_different_shape(
                image_one, image_two)
        difference = cv2.subtract(image_one, image_two)
        if not self.is_same(difference):
            self.diff_found = True
            print('{}Difference detected{}'.format(bcolors.FAIL, bcolors.ENDC))
            print('{}Outputting file {}{}'.format(
                bcolors.FAIL, path_name, bcolors.ENDC))
            diff = cv2.addWeighted(image_one, 0.2, difference, 1, 0)
            all_viz = np.concatenate([image_one, diff, image_two], axis=1)
            cv2.imwrite(os.path.join(directory, path_name), all_viz)
        else:
            self.diff_found = False
            # cv2.imwrite(os.path.join(directory, 'match_one.png'), image_one)
            # cv2.imwrite(os.path.join(directory, 'match_two.png'), image_two)
            print('{}MATCH{}'.format(bcolors.OKBLUE, bcolors.ENDC))
        return (self.diff_found, path_name)

    def compare_data(self):
        print('\nComparing screenshots between URLs.')
        print('As user: {}'.format(self.user))
        print('Browser: {}'.format(self.browser))
        print('First URL: {}'.format(self.prod_url))
        print('Second URL: {}'.format(self.rc_url))
        print('Item type: {}'.format(self.item_type))
        print('Click path: {}'.format(
            None if self.click_path is None else self.click_path.__name__))
        result = self.compute_image_difference()
        print('Distance metric: {}'.format(self.diff_distance_metric))
        return result


################
# Click paths. #
################

# --- Genome browsers. ---

class OpenUCSCGenomeBrowser(object):
    """
    Defines clicks required to open UCSC trackhub from Experiment page for
    given assembly.
    """

    def __init__(self, driver, assembly):
        self.driver = driver
        self.assembly = assembly
        self.perform_action()

    def perform_action(self):
        current_window = self.driver.current_window_handle
        time.sleep(1)
        for y in self.driver.find_elements_by_tag_name(ExperimentPage.all_buttons_tag_name):
            try:
                if y.text == 'Visualize':
                    y.click()
                    self.driver.wait.until(EC.element_to_be_clickable(
                        (By.CLASS_NAME, VisualizeModal.modal_class)))
                    break
            except:
                pass
        modal = self.driver.wait.until(
            EC.element_to_be_clickable((By.CLASS_NAME, VisualizeModal.modal_class)))
        UCSC_links = modal.find_elements_by_partial_link_text(
            VisualizeModal.UCSC_link_partial_link_text)
        for link in UCSC_links:
            if self.assembly in link.get_attribute("href"):
                print('Opening genome browser')
                link.click()
                break
        time.sleep(1)
        self.driver.switch_to_window([h for h in self.driver.window_handles
                                      if h != current_window][0])
        self.driver.wait.until(EC.element_to_be_clickable(
            (By.ID, UCSCGenomeBrowser.zoom_one_id)))
        time.sleep(3)


class OpenUCSCGenomeBrowserGRCh38(object):
    """
    Opens UCSC browser with GRCh38 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'hg38')


class OpenUCSCGenomeBrowserHG19(object):
    """
    Opens UCSC browser with hg19 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'hg19')


class OpenUCSCGenomeBrowserMM9(object):
    """
    Opens UCSC browser with mm9 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'mm9')


class OpenUCSCGenomeBrowserMM10(object):
    """
    Opens UCSC browser with mm10 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'mm10')


class OpenUCSCGenomeBrowserMM10Minimal(object):
    """
    Opens UCSC browser with mm10-minimal assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'mm10')


class OpenUCSCGenomeBrowserDM3(object):
    """
    Opens UCSC browser with dm3 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'dm3')


class OpenUCSCGenomeBrowserDM6(object):
    """
    Opens UCSC browser with dm6 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'dm6')


class OpenUCSCGenomeBrowserCE10(object):
    """
    Opens UCSC browser with ce10 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'ce10')


class OpenUCSCGenomeBrowserCE11(object):
    """
    Opens UCSC browser with ce11 assembly.
    """

    def __init__(self, driver):
        OpenUCSCGenomeBrowser(driver, 'ce11')


# --- File downloads. ---

class DownloadFileFromTable(object):
    """
    Download specified filetype from file table.
    """

    def __init__(self, driver, filetype):
        self.driver = driver
        self.filetype = filetype

    def perform_action(self):
        filenames = []
        download_start_times = []
        # Get all links on page.
        elems = self.driver.wait.until(
            EC.presence_of_all_elements_located((By.XPATH, '//span/a')))
        for elem in elems:
            # Find and click on first link with filetype.
            if self.filetype in elem.get_attribute('href'):
                filename = urllib.request.unquote(elem.get_attribute('href').split(
                    '/')[-1])
                download_start_time = time.time()
                elem.click()
                print('Downloading {} from {}'.format(
                    filename, elem.get_attribute('href')))
                filenames.append(filename)
                download_start_times.append(download_start_time)
                time.sleep(2)
                break
        else:
            raise ValueError('{}WARNING: File not found{}'.format(
                bcolors.FAIL, bcolors.ENDC))
        return filenames, download_start_times


class DownloadBEDFileFromTable(object):
    """
    Download bed.gz file from file table.
    """

    def __init__(self, driver):
        self.filenames, self.download_start_times = DownloadFileFromTable(
            driver, 'bed.gz').perform_action()


class DownloadFileFromModal(object):
    """
    Download file from information modal on file table.
    """

    def __init__(self, driver, full_file_type):
        self.driver = driver
        self.full_file_type = full_file_type

    def perform_action(self):
        elems = self.driver.find_elements_by_xpath(
            ExperimentPage.file_type_column_xpath)
        for elem in elems:
            if elem.text == self.full_file_type:
                filename = urllib.request.unquote(elem.find_element_by_xpath(
                    ExperimentPage.accession_column_relative_xpath).get_attribute('href').split('/')[-1])
                download_start_time = time.time()
                elem.find_element_by_xpath(
                    ExperimentPage.information_button_relative_xpath).click()
                break
        time.sleep(2)
        self.driver.find_element_by_xpath(
            InformationModal.download_icon_xpath).click()
        time.sleep(5)
        print(filename)
        return [filename], [download_start_time]


class DownloadBEDFileFromModal(object):
    """
    Download bed narrowPeak file from information modal.
    """

    def __init__(self, driver):
        self.filenames, self.download_start_times = DownloadFileFromModal(
            driver, 'bed narrowPeak').perform_action()


class DownloadFileFromButton(object):
    """
    Download file based on button text.
    """

    def __init__(self, driver, button_xpath, filename):
        self.driver = driver
        self.button_xpath = button_xpath
        self.filename = filename

    def perform_action(self):
        button = self.driver.wait.until(EC.element_to_be_clickable(
            (By.XPATH, self.button_xpath)))
        filenames = [self.filename]
        download_start_times = [time.time()]
        button.click()
        time.sleep(5)
        return filenames, download_start_times


class DownloadGraphFromExperimentPage(object):
    """
    Download file graph from Experiment page.
    """

    def __init__(self, driver):
        # Filename is accession.png.
        self.filenames, self.download_start_times = DownloadFileFromButton(
            driver, ExperimentPage.download_graph_png_button_xpath,
            '{}.png'.format(driver.current_url.split('/')[-2])).perform_action()


class DownloadTSVFromReportPage(object):
    def __init__(self, driver):
        self.filenames, self.download_start_times = DownloadFileFromButton(
            driver, ReportPage.download_tsv_report_button_xpath, 'report.tsv').perform_action()


class DownloadMetaDataFromSearchPage(object):
    def __init__(self, driver):
        # Get rid of any files.txt from Downloads.
        download_folder = os.path.join(os.path.expanduser('~'), 'Downloads')
        for file in os.listdir(download_folder):
            if ((file.startswith('files') and file.endswith('.txt'))
                    or (file.startswith('metadata') and file.endswith('.tsv'))):
                print('Deleting old files.txt/metadata.tsv')
                try:
                    os.remove(os.path.join(download_folder, file))
                except:
                    pass
        # Click on page.
        DownloadFileFromButton(
            driver, SearchPageList.download_metadata_button_xpath, None).perform_action()
        # Click on modal.
        self.filenames, self.download_start_times = DownloadFileFromButton(
            driver, DownloadModal.download_button_xpath, 'files.txt').perform_action()


class DownloadFileFromFilePage(object):
    def __init__(self, driver):
        self.filenames, self.download_start_times = DownloadFileFromButton(driver, FilePage.download_button_xpath, driver.find_element_by_xpath(
            FilePage.download_button_xpath).get_attribute('href').split('/')[-1]).perform_action()


class DownloadDocuments(object):
    """
    Download all files from documents panel (except Antibody pages).
    """

    def __init__(self, driver):
        self.driver = driver
        self.perform_action()

    def perform_action(self):
        self.filenames = []
        self.download_start_times = []
        elems = self.driver.find_elements_by_xpath(
            DocumentPreview.document_files_xpath)
        for elem in elems:
            filename = urllib.request.unquote(
                elem.get_attribute('href').split('/')[-1])
            download_start_time = time.time()
            elem.click()
            print('Downloading {} from {}'.format(
                filename, elem.get_attribute('href')))
            self.filenames.append(filename)
            self.download_start_times.append(download_start_time)
            time.sleep(2)


class DownloadDocumentsFromAntibodyPage(object):
    """
    Download all files from document panel on Antibody page.
    """

    def __init__(self, driver):
        self.driver = driver
        self.perform_action()

    def perform_action(self):
        self.filenames = []
        self.download_start_times = []
        elems = self.driver.find_elements_by_xpath(
            AntibodyPage.expanded_document_panels_xpath)
        for elem in elems:
            key = elem.get_attribute('href')
            # Filter out non-files.
            if not key.endswith('/'):
                filename = urllib.request.unquote(key.split('/')[-1])
                download_start_time = time.time()
                try:
                     # Safari bug workaround to download PDFs from Antibody page.
                    if ((self.driver.capabilities['browserName'] == 'safari')
                            and key.endswith('pdf')):
                        self.driver.execute_script(
                            'arguments[0].click();', elem)
                    else:
                        elem.click()
                except:
                    print('Error clicking on {}'.format(key))
                    continue
                print('Downloading {} from {}'.format(filename, key))
                self.filenames.append(filename)
                self.download_start_times.append(download_start_time)
                time.sleep(2)


################################################
# Classes for running Selenium tasks robustly. #
################################################


class DataWorker(object):
    def __init__(self, browser, url, user, task, item_type, click_path, server_name, **kwargs):
        self.task_completed = False
        self.browser = browser
        self.task = task
        self.url = url
        self.user = user
        self.item_type = item_type
        self.click_path = click_path
        self.server_name = server_name
        self.kwargs = kwargs

    def new_driver(self):
        self.driver = NewDriver(self.browser, self.url).driver

    def run_task(self):
        try:
            self.new_driver()
            if self.user != 'Public':
                signed_in = SignIn(self.driver, self.user)
                print('Refreshing.')
                self.driver.refresh()
                if not signed_in:
                    raise ValueError('Login stalled.')
            new_task = self.task(self.driver,
                                 self.item_type,
                                 self.click_path,
                                 self.server_name,
                                 **self.kwargs)
            data = new_task.get_data()
            self.task_completed = True
            return data
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            print('{}Exception caught: {}{}'.format(
                bcolors.FAIL, e, bcolors.ENDC))
        finally:
            try:
                self.driver.quit()
            except AttributeError:
                pass


class DataManager(object):
    def __init__(self, browsers, urls, users, task, item_types=[None], click_paths=[None], **kwargs):
        self.browsers = browsers
        self.urls = urls
        self.users = users
        self.task = task
        self.item_types = item_types
        self.click_paths = click_paths
        self.all_data = []
        self.kwargs = kwargs

    def run_tasks(self):
        for user in self.users:
            for browser in self.browsers:
                for url in self.urls:
                    for item_type, click_path in zip(self.item_types, self.click_paths):
                        retry = 5
                        while True:
                            if self.urls[0] == url:
                                server_name = 'prod'
                            else:
                                server_name = 'RC'
                            dw = DataWorker(browser=browser,
                                            url=url,
                                            user=user,
                                            task=self.task,
                                            item_type=item_type,
                                            click_path=click_path,
                                            server_name=server_name,
                                            **self.kwargs)
                            data = dw.run_task()
                            if dw.task_completed:
                                self.all_data.append({'browser': browser,
                                                      'url': url,
                                                      'user': user,
                                                      'item_type': item_type,
                                                      'click_path': click_path,
                                                      'data': data,
                                                      'server_name': server_name})
                                break
                            time.sleep(2)
                            retry -= 1
                            if retry < 1:
                                print('{}WARNING: Task incomplete.{}'.format(
                                    bcolors.FAIL, bcolors.ENDC))
                                break


################################################################
# QANCODE object gets data, compares data using defined tasks. #
################################################################


class QANCODE(object):
    """
    Object to keep track of Task/Comparison combinations and run QA
    process with one method call.
    """

    def __init__(self, rc_url, prod_url='https://encodeproject.org'):
        self.rc_url = rc_url
        self.prod_url = prod_url
        self.browsers = [b for b in BROWSERS]
        self.users = [u for u in USERS]

    def list_methods(self):
        """
        List all possible tests.
        """
        print(*[f for f in sorted(dir(QANCODE)) if callable(getattr(QANCODE, f))
                and not f.startswith('__') and not f.startswith('_')], sep='\n')

    def compare_facets(self,
                       browsers='all',
                       users='all',
                       item_types='all',
                       task=GetFacetNumbers,
                       url_comparison=True,
                       browser_comparison=True):
        """
        Gets RC URL facet numbers and compares them to production URL facet
        numbers for given item_type, browser, user.
        """
        # Define item type pages (search and matrix views) to check.
        all_item_types = [
            '/search/?type=Experiment',
            '/search/?type=File',
            '/search/?type=AntibodyLot',
            '/search/?type=Biosample',
            '/search/?type=Dataset',
            '/search/?type=FileSet',
            '/search/?type=Annotation',
            '/search/?type=Series',
            '/search/?type=OrganismDevelopmentSeries',
            '/search/?type=UcscBrowserComposite',
            '/search/?type=ReferenceEpigenome',
            '/search/?type=Project',
            '/search/?type=ReplicationTimingSeries',
            '/search/?type=PublicationData',
            '/search/?type=MatchedSet',
            '/search/?type=TreatmentConcentrationSeries',
            '/search/?type=TreatmentTimeSeries',
            '/search/?type=Target',
            '/search/?type=Pipeline',
            '/search/?type=Publication',
            '/search/?type=Software',
            '/matrix/?type=Experiment',
            '/matrix/?type=Annotation'
        ]
        if browsers == 'all':
            browsers = self.browsers
        if users == 'all':
            users = self.users
        if item_types == 'all':
            item_types = [t for t in all_item_types]
        urls = [self.prod_url, self.rc_url]
        click_paths = [None for c in item_types]
        dm = DataManager(browsers=browsers,
                         urls=urls,
                         users=users,
                         item_types=item_types,
                         click_paths=click_paths,
                         task=task)
        dm.run_tasks()
        if url_comparison:
            for browser in browsers:
                for user in users:
                    for item_type in item_types:
                        cfn_url = CompareFacetNumbersBetweenURLS(browser=browser,
                                                                 user=user,
                                                                 prod_url=self.prod_url,
                                                                 rc_url=self.rc_url,
                                                                 item_type=item_type,
                                                                 click_path=None,
                                                                 all_data=dm.all_data)
                        cfn_url.compare_data()
        if browser_comparison:
            for url in urls:
                for user in users:
                    for item_type in item_types:
                        cfn_browser = CompareFacetNumbersBetweenBrowsers(user=user,
                                                                         url=url,
                                                                         item_type=item_type,
                                                                         browsers=browsers,
                                                                         all_data=dm.all_data)
                        cfn_browser.compare_data()

    @staticmethod
    def _expand_action_list(actions):
        """
        Returns item_types and click_paths given list of tuples.
        """
        item_types = [t[0] for t in actions]
        click_paths = [p[1] for p in actions]
        return item_types, click_paths

    def _parse_arguments(self,
                         browsers,
                         users,
                         item_types,
                         click_paths,
                         action_tuples,
                         actions,
                         admin_only_actions,
                         public_only_actions):
        if browsers == 'all':
            browsers = self.browsers
        if users == 'all':
            users = self.users
        if action_tuples is not None:
            item_types, click_paths = self._expand_action_list(action_tuples)
        else:
            if item_types == 'all':
                item_types, click_paths = self._expand_action_list(actions)
            elif item_types == 'admin':
                item_types, click_paths = self._expand_action_list(
                    admin_only_actions)
            elif item_types == 'public':
                item_types, click_paths = self._expand_action_list(
                    public_only_actions)
            else:
                if len(item_types) == len(click_paths):
                    pass
                elif len(click_paths) == 1:
                    # Broadcast single click_path (e.g. None) to all user-defined item_types.
                    click_paths = [click_paths[0] for t in item_types]
                else:
                    raise ValueError(
                        'item_types and click_paths must have same length')
        return browsers, users, item_types, click_paths

    def find_differences(self,
                         browsers='all',
                         users='all',
                         action_tuples=None,
                         item_types='all',
                         click_paths=[None],
                         task=GetScreenShot):
        """
        Does image diff for given item_types. If click_path defined will
        perform that action before taking screenshot.
        """
        # Tuple of (item_type, click_path)
        actions = [('/', None),
                   ('/targets/?status=deleted', None),
                   ('/antibodies/?status=deleted', None),
                   ('/search/?type=Biosample&status=deleted', None),
                   ('/experiments/ENCSR000CWD/', None),
                   ('/biosamples/ENCBS574ZRE/', None),
                   ('/biosamples/ENCBS883DWI/', None),
                   ('/experiments/ENCSR985KAT/', None),
                   ('/biosamples/ENCBS298YPF/', None),
                   ('/biosamples/ENCBS142DVU/', None),
                   ('/biosamples/ENCBS562NPI/', None),
                   ('/human-donors/ENCDO999JZG/', None),
                   ('/biosamples/ENCBS615YKY/', None),
                   ('/search/?searchTerm=puf60&type=Target', None),
                   ('/experiments/ENCSR502NRF/', None),
                   ('/experiments/ENCSR000AEH/', None),
                   ('/search/?searchTerm=ENCSR000AEH&type=Experiment', None),
                   ('/experiments/ENCSR000CPG/', None),
                   ('/search/?searchTerm=ENCSR000CPG&type=Experiment', None),
                   ('/experiments/ENCSR000BPF/', None),
                   ('/search/?searchTerm=ENCSR000BPF&type=Experiment', None),
                   ('/experiments/ENCSR178NTX/', None),
                   ('/experiments/ENCSR651NGR/', None),
                   ('/search/?searchTerm=ENCSR651NGR&type=Experiment', None),
                   ('/antibodies/ENCAB000AEH/', None),
                   ('/search/?searchTerm=ENCAB000AEH&type=AntibodyLot', None),
                   ('/antibodies/ENCAB000AIW/', None),
                   ('/search/?searchTerm=ENCAB000AIW&type=AntibodyLot', None),
                   ('/biosamples/ENCBS000AAA/', None),
                   ('/search/?searchTerm=ENCBS000AAA&type=Biosample', None),
                   ('/biosamples/ENCBS030ENC/', None),
                   ('/search/?searchTerm=ENCBS030ENC', None),
                   ('/biosamples/ENCBS098ENC/', None),
                   ('/search/?searchTerm=ENCBS098ENC&type=Biosample', None),
                   ('/biosamples/ENCBS619ENC/', None),
                   ('/search/?searchTerm=ENCBS619ENC&type=Biosample', None),
                   ('/biosamples/ENCBS286AAA/', None),
                   ('/search/?searchTerm=ENCBS286AAA&type=Biosample', None),
                   ('/biosamples/ENCBS314VPT/', None),
                   ('/search/?searchTerm=ENCBS314VPT&type=Biosample', None),
                   ('/biosamples/ENCBS808BUA/', None),
                   ('/search/?searchTerm=ENCBS808BUA&type=Biosample', None),
                   ('/targets/AARS-human/', None),
                   ('/targets/FLAG-GABP-human/', None),
                   ('/search/?type=Target&name=AARS-human', None),
                   ('/ucsc-browser-composites/ENCSR707NXZ/', None),
                   ('/treatment-time-series/ENCSR210PYP/', None),
                   ('/search/?searchTerm=WASP&type=Software', None),
                   ('/publications/67e606ae-abe7-4510-8ebb-cfa1fefe5cfa/', None),
                   ('/search/?searchTerm=PMID%3A25164756', None),
                   ('/biosamples/ENCBS632MTU/', None),
                   ('/biosamples/ENCBS464EKT/', None),
                   ('/annotations/ENCSR790GQB/', None),
                   ('/publications/b2e859e6-3ee7-4274-90be-728e0faaa8b9/', None),
                   ('/pipelines/', None),
                   ('/pipelines/ENCPL210QWH/', None),
                   ('/pipelines/ENCPL002LPE/', None),
                   ('/pipelines/ENCPL002LSE/', None),
                   ('/rna-seq/long-rnas/', None),
                   ('/pipelines/ENCPL337CSA/', None),
                   ('/rna-seq/small-rnas/', None),
                   ('/pipelines/ENCPL444CYA/', None),
                   ('/microrna/microrna-seq/', None),
                   ('/pipelines/ENCPL278BTI/', None),
                   ('/microrna/microrna-counts/', None),
                   ('/pipelines/ENCPL122WIM/', None),
                   ('/rampage/', None),
                   ('/pipelines/ENCPL220NBH/', None),
                   ('/pipelines/ENCPL272XAE/', None),
                   ('/pipelines/ENCPL272XAE/', None),
                   ('/chip-seq/histone/', None),
                   ('/pipelines/ENCPL138KID/', None),
                   ('/pipelines/ENCPL493SGC/', None),
                   ('/chip-seq/transcription_factor/', None),
                   ('/pipelines/ENCPL001DNS/', None),
                   ('/pipelines/ENCPL002DNS/', None),
                   ('/data-standards/dnase-seq/', None),
                   ('/atac-seq/', None),
                   ('/pipelines/ENCPL985BLO/', None),
                   ('/data/annotations/', None),
                   ('/help/rest-api/', None),
                   ('/about/experiment-guidelines/', None),
                   ('/data-standards/terms/', None)]
        admin_only_actions = [('/biosamples/ENCBS681LAC/', None),
                              ('/search/?searchTerm=ENCBS681LAC&type=Biosample', None)]
        public_only_actions = [('/experiments/?status=deleted', None)]
        browsers, users, item_types, click_paths = self._parse_arguments(browsers=browsers,
                                                                         users=users,
                                                                         item_types=item_types,
                                                                         click_paths=click_paths,
                                                                         action_tuples=action_tuples,
                                                                         actions=actions,
                                                                         admin_only_actions=admin_only_actions,
                                                                         public_only_actions=public_only_actions)
        urls = [self.prod_url, self.rc_url]
        results = []
        with tempfile.TemporaryDirectory() as td:
            dm = DataManager(browsers=browsers,
                             urls=urls,
                             users=users,
                             item_types=item_types,
                             click_paths=click_paths,
                             task=task,
                             temp_dir=td)
            dm.run_tasks()
            for browser in browsers:
                for user in users:
                    for item_type, click_path in zip(item_types, click_paths):
                        css = CompareScreenShots(browser=browser,
                                                 user=user,
                                                 prod_url=self.prod_url,
                                                 rc_url=self.rc_url,
                                                 item_type=item_type,
                                                 click_path=click_path,
                                                 all_data=dm.all_data)
                        result = css.compare_data()
                        results.append(result)
        return results

    def check_trackhubs(self, browsers=['Safari'], users=['Public'], action_tuples=None):
        """
        Runs find_differences() image diff for selected list of trackhub
        actions.
        """
        print('Running check trackhubs')
        trackhub_actions = [('/experiments/ENCSR502NRF/',
                             OpenUCSCGenomeBrowserGRCh38),
                            ('/experiments/ENCSR502NRF/',
                             OpenUCSCGenomeBrowserHG19),
                            ('/experiments/ENCSR985KAT/',
                             OpenUCSCGenomeBrowserHG19),
                            ('/experiments/ENCSR426UUG/',
                             OpenUCSCGenomeBrowserGRCh38),
                            ('/experiments/ENCSR293WTN/',
                             OpenUCSCGenomeBrowserMM9),
                            ('/experiments/ENCSR335LKF/',
                             OpenUCSCGenomeBrowserMM10),
                            ('/experiments/ENCSR922ESH/',
                             OpenUCSCGenomeBrowserDM3),
                            ('/experiments/ENCSR671XAK/',
                             OpenUCSCGenomeBrowserDM6),
                            ('/experiments/ENCSR422XRE/',
                             OpenUCSCGenomeBrowserCE10),
                            ('/experiments/ENCSR686FKU/',
                             OpenUCSCGenomeBrowserCE11),
                            ('/publication-data/ENCSR764APB/',
                             OpenUCSCGenomeBrowserHG19),
                            ('/projects/ENCSR295OIE/',
                             OpenUCSCGenomeBrowserHG19),
                            ('/annotations/ENCSR212BHV/',
                             OpenUCSCGenomeBrowserHG19),
                            ('/experiments/ENCSR000CJR/',
                             OpenUCSCGenomeBrowserHG19),
                            ('/search/?type=Experiment&assembly=hg19&target.investigated_as=RNA+binding+protein&assay_title=ChIP-seq&replicates.library.biosample.biosample_type=primary+cell',
                             OpenUCSCGenomeBrowserHG19),
                            ('/search/?type=Experiment&assembly=GRCh38&assay_title=shRNA+RNA-seq&target.investigated_as=transcription+factor&month_released=October%2C+2014',
                             OpenUCSCGenomeBrowserGRCh38),
                            ('/search/?type=Experiment&assembly=mm9&assay_title=Repli-chip',
                             OpenUCSCGenomeBrowserMM9),
                            ('/search/?type=Experiment&assembly=mm10&assay_title=microRNA-seq&month_released=January%2C+2016',
                             OpenUCSCGenomeBrowserMM10),
                            ('/search/?type=Experiment&assembly=dm3&status=released&replicates.library.biosample.biosample_type=whole+organisms&assay_title=total+RNA-seq',
                             OpenUCSCGenomeBrowserDM3),
                            ('/search/?type=Experiment&assembly=dm6&replicates.library.biosample.life_stage=wandering+third+instar+larva',
                             OpenUCSCGenomeBrowserDM6),
                            ('/search/?type=Experiment&assembly=ce10&target.investigated_as=transcription+factor&replicates.library.biosample.life_stage=L4+larva',
                             OpenUCSCGenomeBrowserCE10),
                            ('/search/?type=Experiment&assembly=ce11&target.investigated_as=recombinant+protein&replicates.library.biosample.life_stage=late+embryonic&replicates.library.biosample.life_stage=L4+larva',
                             OpenUCSCGenomeBrowserCE11),
                            ('/search/?searchTerm=hippocampus&type=Experiment',
                             OpenUCSCGenomeBrowserHG19)]
        if action_tuples is None:
            action_tuples = trackhub_actions
        self.find_differences(users=users, browsers=browsers,
                              action_tuples=action_tuples)

    def check_permissions(self, browsers=['Safari'], users=['Public']):
        """
        Runs find_differences() image diff on permission check pages.
        """
        print('Running check permissions')
        permission_actions = [('/experiments/ENCSR524OCB/', None),
                              ('/experiments/ENCSR000EFT/', None),
                              ('/biosamples/ENCBS643IYW/', None),
                              ('/experiments/ENCSR466YGC/', None),
                              ('/experiments/ENCSR255XZG/', None),
                              ('/experiments/ENCSR115BCB/', None),
                              ('/files/ENCFF752JWY/', None),
                              ('/targets/2L52.1-celegans/', None),
                              ('/targets/CG15455-dmelanogaster/', None),
                              ('/software/dnase-eval-bam-se/', None),
                              ('/software/atac-seq-software-tools/', None),
                              ('/software/trimAdapters.py/', None),
                              ('/software/bigwigaverageoverbed/', None),
                              ('/pipelines/ENCPL493SGC/', None),
                              ('/pipelines/ENCPL035XIO/', None),
                              ('/pipelines/ENCPL568PWV/', None),
                              ('/pipelines/e02448b1-9706-4e7c-b31b-78c921d58f0b/', None),
                              ('/pipelines/ENCPL734EDH/', None),
                              ('/pipelines/ENCPL983UFZ/', None),
                              ('/pipelines/ENCPL631XPY/', None),
                              ('/publications/b2e859e6-3ee7-4274-90be-728e0faaa8b9/', None),
                              ('/publications/a4db2c6d-d1a3-4e31-b37b-5cc7d6277548/', None),
                              ('/publications/16c77add-1bfb-424b-8cab-498ac1e5f6ed/', None),
                              ('/publications/da2f7542-3d99-48f6-a95d-9907dd5e2f81/', None),
                              ('/internal-data-use-policy/', None),
                              ('/tutorials/encode-users-meeting-2016/logistics/', None),
                              ('/2017-06-09-release/', None)]
        self.find_differences(users=users, browsers=browsers,
                              action_tuples=permission_actions)

    def check_downloads(self,
                        browsers='all',
                        users='all',
                        action_tuples=None,
                        item_types='all',
                        click_paths=[None],
                        task=DownloadFiles,
                        urls='all',
                        delete=True):
        """
        Clicks download button and checks download folder for file.
        """
        print('Running check downloads')
        actions = [('/experiments/ENCSR810WXH/', DownloadBEDFileFromTable),
                   ('/experiments/ENCSR966YYJ/', DownloadBEDFileFromModal),
                   ('/experiments/ENCSR810WXH/', DownloadGraphFromExperimentPage),
                   ('/experiments/ENCSR810WXH/', DownloadDocuments),
                   ('/ucsc-browser-composites/ENCSR707NXZ/', DownloadDocuments),
                   ('/antibodies/ENCAB749XQY/', DownloadDocumentsFromAntibodyPage),
                   ('/report/?searchTerm=nose&type=Biosample',
                    DownloadTSVFromReportPage),
                   ('/search/?type=Experiment&searchTerm=nose',
                    DownloadMetaDataFromSearchPage),
                   ('/files/ENCFF931OLL/', DownloadFileFromFilePage),
                   ('/files/ENCFF291ELS/', DownloadFileFromFilePage)]
        admin_only_actions = []
        public_only_actions = []
        browsers, users, item_types, click_paths = self._parse_arguments(browsers=browsers,
                                                                         users=users,
                                                                         item_types=item_types,
                                                                         click_paths=click_paths,
                                                                         action_tuples=action_tuples,
                                                                         actions=actions,
                                                                         admin_only_actions=admin_only_actions,
                                                                         public_only_actions=public_only_actions)
        if urls == 'all':
            urls = [self.prod_url, self.rc_url]
        dm = DataManager(browsers=browsers,
                         urls=urls,
                         users=users,
                         item_types=item_types,
                         click_paths=click_paths,
                         task=task,
                         delete=delete)
        dm.run_tasks()

    @staticmethod
    def _create_authentication_header(headers, authid, authpw):
        headers['Authorization'] = requests.auth._basic_auth_str(
            authid, authpw)
        return headers

    @staticmethod
    def _block_production_edit(url):
        # Don't test production.
        if 'encodeproject.org' in url:
            raise SystemError('No editing production.')
        return None

    def _get_auth_credentials(self, user):
        if user == 'Public':
            return None, None
        cred_file = os.path.expanduser('~/qa_credentials.json')
        with open(cred_file) as f:
            creds = [(k['authid'], k['authpw']) for k
                     in json.load(f) if k['username'] == user]
        if not creds:
            raise ValueError('User not found.')
        return creds[0]

    def check_requests(self):
        """
        Runs post, patch, and get requests as different users.
        """
        url = self.rc_url
        self._block_production_edit(url)
        lab_submitter = USERS[2]
        admin = 'admin'
        # List of tuples:
        # ('suburl', [{payloads}], [(user, expected_status_code)])
        action_dict = {
            'patch': [
                ('/experiments/ENCSR000CUS/',
                 [{'description': 'test'}],
                 [('Public', 400),
                  (lab_submitter, 403)]),
                ('/experiments/ENCSR000CUS/',
                 [{'status': 'deleted'},
                  {'status': 'archived'},
                  {'status': 'proposed'},
                  {'status': 'ready for review'},
                  {'status': 'released'},
                  {'status': 'started'},
                  {'status': 'submitted'},
                  {'status': 'replaced'}],
                 [(admin, 200)]),
                ('/experiments/ENCSR035DLJ/',
                 [{'alternate_accessions': ['ENCSR000CUS']},
                  {'alternate_accessions': []}],
                 [(admin, 200)]),
                ('35f91f16-dcef-4ab2-90bd-3928b0db9a60',
                 [{'status': 'revoked'}],
                 [(admin, 200)]),
                ('/files/ENCFF002BYE/',
                 [{'status': 'deleted'},
                  {'status': 'in progress'},
                  {'status': 'released'},
                  {'status': 'replaced'}],
                 [(admin, 200)]),
                ('4dc1fbd3-6692-42fa-b710-03eaba9263c1',
                 [{'status': 'revoked'}],
                 [(admin, 200)])
            ],
            'post': [
                ('/experiments/',
                 [{'description': 'test post experiment',
                   'assay_term_name': 'ChIP-seq',
                   'biosample_term_id': 'CL:0010001',
                   'biosample_type': 'primary cell',
                   'biosample_term_name': 'Stromal cell of bone marrow',
                   'target': '/targets/SMAD6-human/',
                   'award': '/awards/U41HG006992/',
                   'lab': '/labs/thomas-gingeras/',
                   'references': ['PMID:18229687', 'PMID:25677182']}],
                 [('Public', 400),
                  (lab_submitter, 201),
                  (admin, 201)])
            ],
            'get': [
                ('/experiments/ENCSR082IHY/',
                 [None],
                 [('Public', 403),
                  (lab_submitter, 403),
                  (admin, 200)]),
                ('/experiments/ENCSR000CUS',
                 [None],
                 [('Public', 200),
                  (lab_submitter, 200),
                  (admin, 200)])
            ]
        }
        for k, v in action_dict.items():
            for item in v:
                request_url = urllib.parse.urljoin(url, item[0])
                for user, status_code in item[2]:
                    headers = {'content-type': 'application/json',
                               'accept': 'application/json'}
                    (authid, authpw) = self._get_auth_credentials(user)
                    if authid is not None:
                        headers = self._create_authentication_header(
                            headers, authid, authpw)
                    for payload in item[1]:
                        print('Trying to {} {} with {} as user {} (expecting status_code {})'.format(
                            k, request_url, payload, user, status_code))
                        r = requests.request(
                            k, url=request_url, headers=headers, data=json.dumps(payload))
                        try:
                            print(r.status_code)
                            assert r.status_code == status_code
                            print('{}{} SUCCESSFUL{}'.format(
                                bcolors.OKBLUE, k.upper(), bcolors.ENDC))
                        except AssertionError:
                            print('{}{} FAILURE{}'.format(
                                bcolors.FAIL, k.upper(), bcolors.ENDC))
                            print(r.text)

    def _add_rc_to_keypairs(self, url):
        """
        Gets production keypair and copies it to rc_url server.
        """
        keypairs = os.path.expanduser('~/keypairs.json')
        try:
            with open(keypairs, 'r') as f:
                data = json.load(f)
                prod_data = data['prod']
                authid, authpw = prod_data['key'], prod_data['secret']
                data['current_rc'] = {'server': url,
                                      'key': authid,
                                      'secret': authpw}
            # Overwrite.
            with open(keypairs, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(e)
            raise

    def check_tools(self):
        """
        Runs pyencoded-tools against RC.
        """
        url = self.rc_url
        self._block_production_edit(url)
        self._add_rc_to_keypairs(url)
        key = '--key current_rc'
        # Expected outut a very weak check.
        tools = [{'name': 'ENCODE_get_fields.py',
                  'command': '{} {} {}  --infile ENCSR000CUS --field status',
                  'expected_output': 'accession\tstatus\r\nENCSR000CUS\trevoked\r\n'},
                 {'name': 'ENCODE_patch_set.py',
                  'command': '{} {} {} --accession ENCSR000CUS --field status --data revoked',
                  'expected_output': 'OBJECT: ENCSR000CUS\nOLD DATA: status'
                  ' revoked\nNEW DATA: status revoked'},
                 {'name': 'ENCODE_release.py',
                  'command': '{} {} {} --infile ENCSR000CUS',
                  'expected_output': 'Data written to file Release_report.txt'},
                 {'name': 'ENCODE_submit_files.py',
                  'command': '{} {} permissions_qa_scripts/Test_submit_files.csv {}',
                  'expected_output': "'file_size': 23972104"}
                 ]
        # Get relative Python executable.
        python_executor = sys.executable
        for tool in tools:
            print('Running {}'.format(tool['name']))
            command = tool['command'].format(
                python_executor, tool['name'], key)
            print(command)
            output = subprocess.check_output(
                command, shell=True).decode('utf-8').strip()
            try:
                assert ((output == tool['expected_output'].strip())
                        or (tool['expected_output'] in output))
                print('{}{} SUCCESSFUL{}'.format(
                    bcolors.OKBLUE, tool['name'].upper(), bcolors.ENDC))
            except AssertionError:
                print('{}{} FAILURE{}'.format(
                    bcolors.FAIL, tool['name'].upper(), bcolors.ENDC))
                print('Expected: ')
                print(tool['expected_output'])
                print('Actual: ')
                print(output)
