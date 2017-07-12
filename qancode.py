import getpass
import json
import time
import os

from abc import ABCMeta, abstractmethod
from collections import defaultdict
from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By


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

# Run facet comparison for Experiment items in Safari as public and
# admin user.
>>> qa.compare_facets(users=['Public', 'encxxxtest@gmail.com'],
                      browsers=['Safari'],
                      item_types=['/search/?type=Experiment'])

Will return comparison of data between production and RC for a given browser
as well as comparison of data between browsers for a given URL.

Required
--------
Selenium webdriver for Chrome, Firefox, Safari.

To run as any user != Public must create ~/qa_credentials.json file with
list of objects containing username and password fields:

[{"username": "enxxxxtest@gmail.com", "password": "xxxxx"},
 {"username": "encxxxxtest2@gmail.com", "password": "xxxxx"},
 {"username": "encxxxxtest4@gmail.com", "password": "xxxxx"}]

"""


BROWSERS = ['Chrome',
            'Firefox',
            'Safari']

USERS = ['Public',
         'encoded.test@gmail.com',
         'encoded.test2@gmail.com',
         'encoded.test4@gmail.com']


class bcolors:
    OKBLUE = '\x1b[36m'
    OKGREEN = '\x1b[1;32m'
    WARNING = '\x1b[33m'
    FAIL = '\x1b[31m'
    ENDC = '\x1b[0m'


class NewDriver(object):
    def __init__(self, browser, url):
        print('Opening {} in {}'.format(url, browser))
        if browser == 'Safari':
            self.driver = webdriver.Safari(
                port=0, executable_path='/Applications/Safari Technology Preview.app/Contents/MacOS/safaridriver')
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
                    (By.CLASS_NAME, 'auth0-lock-header-logo')))
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

    def login_two_step(self):
        user_id = self.driver.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '#username')))
        user_id.send_keys(self.creds[0]['username'])
        password = self.driver.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '#password')))
        pw = getpass.getpass()
        password.send_keys(pw)
        pw = None
        submit = self.driver.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '#login > input')))
        submit.click()
        send_sms = self.driver.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '#sms-send > input.submit-button')))
        send_sms.click()
        code = self.driver.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '#otp')))
        verification = input('Authentication code: ')
        code.send_keys(verification)
        submit = self.driver.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '#otp-box > div > input.go-button')))
        submit.click()

    def sign_in(self):
        print('Logging in as {}'.format(self.user))
        original_window_handle = self.driver.window_handles[0]
        self.driver.switch_to_window(original_window_handle)
        login_button = self.driver.wait.until(EC.element_to_be_clickable(
            (By.PARTIAL_LINK_TEXT, 'Submitter sign-in')))
        try:
            login_button.click()
            self.driver.wait.until(EC.presence_of_element_located(
                (By.CLASS_NAME, 'auth0-lock-header-logo')))
        except TimeoutException:
            login_button.click()
        try:
            google_button = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, '#auth0-lock-container-1 > div > div.auth0-lock-center > form > div > div > div:nth-child(3) > span > div > div > div > div > div > div > div > div > div > div.auth0-lock-social-buttons-container > button:nth-child(2) > div.auth0-lock-social-button-icon')))
            google_button.click()
        except TimeoutException:
            # Hack to find button in Safari.
            for button in self.driver.find_elements_by_tag_name('button'):
                if '@' in button.text:
                    button.click()
                    break
            self.wait_for_modal_to_quit()
            return None
        try:
            user_id = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, '#identifierId')))
        except TimeoutException:
            new_window_handle = [
                h for h in self.driver.window_handles if h != original_window_handle][0]
            self.driver.switch_to_window(new_window_handle)
            user_id = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, '#identifierId')))
        user_id.send_keys(self.creds[0]['username'])
        next_button = self.driver.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
                                                                         '#identifierNext > content > span')))
        next_button.click()
        try:
            pw = self.driver.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, '#password > div.aCsJod.oJeWuf > div > div.Xb9hP > input')))
            pw.send_keys(self.creds[0]['password'])
            next_button = self.driver.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
                                                                             '#passwordNext > content > span')))
            next_button.click()
        except TimeoutException:
            if self.is_two_step():
                self.login_two_step()
            else:
                new_window_handle = [
                    h for h in self.driver.window_handles if h != original_window_handle][0]
                self.driver.switch_to_window(new_window_handle)
                next_button = self.driver.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
                                                                                 '#passwordNext > content > span')))
                next_button.click()
        self.driver.switch_to_window(original_window_handle)
        self.wait_for_modal_to_quit()
        return None


class SeleniumTask(metaclass=ABCMeta):
    """
    ABC for defining a Selenium task.
    """

    def __init__(self, driver, item_type):
        self.driver = driver
        self.item_type = item_type

    @abstractmethod
    def get_data(self):
        pass


class GetFacetNumbers(SeleniumTask):
    """
    Implementation of Task for getting facet number data.
    """

    def get_data(self):
        if self.item_type is None:
            try:
                data_button = self.driver.wait_long.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, '#main > ul > li:nth-child(1) > a')))
            except TimeoutException:
                data_button = self.driver.wait_long.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, '#main > ul > li:nth-child(1) > button')))
            data_button.click()
            search_button = self.driver.wait_long.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, '#main > ul > li.dropdown.open > ul > li:nth-child(2) > a')))
            search_button.click()
        else:
            type_url = self.driver.current_url + self.item_type
            print('Getting type: {}'.format(self.item_type))
            self.driver.get(type_url)
        try:
            facet_box = self.driver.wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, 'facets')))
        except TimeoutError:
            search_button.click()
            facet_box = self.driver.wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, 'facets')))
        see_more_buttons = facet_box.find_elements_by_css_selector(
            '#content > div > div > div > div > div.col-sm-5.col-md-4.col-lg-3 > div > div > div > ul > div.pull-right > small > button')
        for button in see_more_buttons:
            button.click()
        facets = self.driver.find_elements_by_class_name('facet')
        data_dict = defaultdict(list)
        for facet in facets:
            title = facet.find_element_by_css_selector(
                'h5').text.replace(':', '').strip()
            categories = [
                c.text for c in facet.find_elements_by_class_name('facet-item')]
            print('Collecting values in {}.'.format(title))
            numbers = [n.text for n in facet.find_elements_by_class_name(
                'pull-right') if n.text != '']
            assert len(categories) == len(numbers)
            if title in data_dict.keys():
                title_number = len([t for t in data_dict.keys()
                                    if t.startswith(title)]) + 1
                title = title + str(title_number)
            data_dict[title] = list(zip(categories, numbers))
        return data_dict


class BrowserComparison(metaclass=ABCMeta):
    """
    ABC for comparing data between browsers.
    """

    def __init__(self, user, url, item_type, all_data):
        self.all_data = all_data
        self.user = user
        self.url = url
        self.item_type = item_type
        self.url_data = [d for d in all_data if ((d['user'] == user)
                                                 and (d['item_type'] == item_type)
                                                 and (d['url'] == url))]

    @abstractmethod
    def compare_data(self):
        pass


class CompareFacetNumbersBetweenBrowsers(BrowserComparison):
    """
    Implementation of BrowserComparison for facet numbers.
    """

    def compare_data(self):
        """
        Return comparison of data between browsers given server (prod/RC),
        user, item_type.
        """
        print('Comparing data between browsers.')
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


class URLComparison(metaclass=ABCMeta):
    """
    ABC for comparing data between prod and RC given browser and user.
    """

    def __init__(self, browser, user, prod_url, rc_url, item_type, all_data):
        self.browser = browser
        self.user = user
        self.all_data = all_data
        self.prod_url = prod_url
        self.rc_url = rc_url
        self.item_type = item_type
        self.prod_data = [d['data'] for d in all_data
                          if ((d['url'] == prod_url)
                              and (d['user'] == user)
                              and (d['browser'] == browser)
                              and (d['item_type'] == item_type))]
        self.rc_data = [d['data'] for d in all_data
                        if ((d['url'] == rc_url)
                            and (d['user'] == user)
                            and (d['browser'] == browser)
                            and (d['item_type'] == item_type))]
        assert len(self.prod_data) == len(self.rc_data)

    @abstractmethod
    def compare_data(self):
        pass


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


class DataWorker(object):
    def __init__(self, browser, url, user, task, item_type):
        self.task_completed = False
        self.browser = browser
        self.task = task
        self.url = url
        self.user = user
        self.item_type = item_type

    def new_driver(self):
        self.driver = NewDriver(self.browser, self.url).driver

    def run_task(self):
        try:
            self.new_driver()
            if self.user != 'Public':
                SignIn(self.driver, self.user)
            new_task = self.task(self.driver, self.item_type)
            data = new_task.get_data()
            self.task_completed = True
            return data
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            print('Exception caught: {}.'.format(e))
        finally:
            try:
                self.driver.quit()
            except AttributeError:
                pass


class DataManager(object):
    def __init__(self, browsers, urls, users, task, item_types=[None]):
        self.browsers = browsers
        self.urls = urls
        self.users = users
        self.task = task
        self.item_types = item_types
        self.all_data = []

    def run_tasks(self):
        for user in self.users:
            for browser in self.browsers:
                for url in self.urls:
                    for item_type in self.item_types:
                        retry = 10
                        while retry > 0:
                            dw = DataWorker(browser=browser,
                                            url=url,
                                            user=user,
                                            task=self.task,
                                            item_type=item_type)
                            data = dw.run_task()
                            if dw.task_completed:
                                self.all_data.append({'browser': browser,
                                                      'url': url,
                                                      'user': user,
                                                      'item_type': item_type,
                                                      'data': data})
                                break
                            time.sleep(2)
                            retry -= 1
                            if retry < 0:
                                raise ValueError('Task incomplete.')


class QANCODE(object):
    """
    Object to keep track of Task/Comparison combinations and run QA
    process with one method call.
    """

    def __init__(self, rc_url, prod_url='https://encodeproject.org'):
        self.rc_url = rc_url
        self.prod_url = prod_url

    def list_methods(self):
        """
        List all possible tests.
        """
        pass

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
            # TODO: Fix get_data to support matrix view.
            #'/matrix/?type=Experiment',
            #'/matrix/?type=Annotation'
        ]
        if browsers == 'all':
            browsers = [b for b in BROWSERS]
        if users == 'all':
            users = [u for u in USERS]
        if item_types == 'all':
            item_types = [t for t in all_item_types]
        urls = [self.prod_url, self.rc_url]
        dm = DataManager(browsers=browsers,
                         urls=urls,
                         users=users,
                         item_types=item_types,
                         task=task)
        dm.run_tasks()
        if browser_comparison:
            for browser in browsers:
                for user in users:
                    for item_type in item_types:
                        cfn_url = CompareFacetNumbersBetweenURLS(browser=browser,
                                                                 user=user,
                                                                 prod_url=self.prod_url,
                                                                 rc_url=self.rc_url,
                                                                 item_type=item_type,
                                                                 all_data=dm.all_data)
                        cfn_url.compare_data()
        if url_comparison:
            for url in urls:
                for user in users:
                    for item_type in item_types:
                        cfn_browser = CompareFacetNumbersBetweenBrowsers(user=user,
                                                                         url=url,
                                                                         item_type=item_type,
                                                                         all_data=dm.all_data)
                        cfn_browser.compare_data()
