/*
 Licensed to the Apache Software Foundation (ASF) under one or more
 contributor license agreements.  See the NOTICE file distributed with
 this work for additional information regarding copyright ownership.
 The ASF licenses this file to You under the Apache License, Version 2.0
 (the "License"); you may not use this file except in compliance with
 the License.  You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

/*
Main script library for the web-based user interface for selfserve.apache.org
*/

const LIB_NAME = '[Selfserve Platform]';

// Standard console logging for debugging purposes
/* eslint no-console: ["error", { allow: ["debug", "info", "warn", "error"] }] */
function log(msg, level = 'info') {
  if (level === 'info') console.info(LIB_NAME, msg);
}

// Simple UUID generator for debugging and oauth requests
function uuid() {
  return Math.random().toString(20).substring(2, 8)
      + Math.random().toString(20).substring(2, 8)
      + Math.random().toString(20).substring(2, 8);
}

// Converts dictionaries to FormData
function toFormData(params) {
  if (!params) return null; // No form data? Return null then.
  if (params instanceof FormData) return params; // Already a FormData object? Just return it then.
  if (params instanceof File) return params; // A File object will also suffice for Fetch.
  // Otherwise, construct from dictionary and return.
  const fd = new FormData();
  Object.entries(params).forEach(([key, value]) => fd.append(key, value));
  return fd;
}

// Basic check for whether sessionStorage is supported or not
function sessionStorageSupported() {
  try {
    const storage = window.sessionStorage;
    storage.setItem('test', 'test');
    storage.removeItem('test');
    return true;
  } catch (e) {
    return false;
  }
}

// Basic GET HTTP call
async function GET(url, params, method = 'GET') {
  const xhrID = uuid();
  const parameters = params || {}; // We want a dict here
  const headers = new Headers();
  headers.append('X-Selfserve-WebUI', 'yes'); // Inform the backend that we will not accept a Realm response
  if (parameters.json) headers.append('Content-Type', 'application/json');

  const data = parameters.json ? JSON.stringify(parameters.json) : toFormData(parameters.data);
  log(`[${xhrID}] Sending ${method} XHR to URL ${url}`);
  const response = await fetch(url, {
    method,
    headers,
    body: data,
  });
  log(`[${xhrID}] Server responded to ${method} ${url} with status: ${response.status}`);
  return response;
}

// Wrappers for all other HTTP methods that are used by this service
const DELETE = (url, options) => GET(url, options, 'DELETE');
const MKCOL = (url, options) => GET(url, options, 'MKCOL');
const PATCH = (url, options) => GET(url, options, 'PATCH');
const POST = (url, options) => GET(url, options, 'POST');
const PROMOTE = (url, options) => GET(url, options, 'PROMOTE');
const PUT = (url, options) => GET(url, options, 'PUT');
const VERIFY = (url, options) => GET(url, options, 'VERIFY');

// OAuth gateway. Ensures OAuth is set up in the client before proceeding
// If/when OAuth is set up, this calls the original callback with the session data
// and any URL query string args
async function OAuthGate(callback) {
  const QSDict = new URLSearchParams(document.location.search);
  if (QSDict.get('action') === 'oauth') { // OAuth callback?
    const OAuthResponse = await GET(`/api/oauth?${QSDict.toString()}`);
    if (OAuthResponse.status === 200) {
      if (sessionStorageSupported()) {
        const OriginURL = window.sessionStorage.getItem('asp_origin');
        // Do we have a stored URL to redirect back to, now that OAuth worked?
        if (OriginURL) {
          window.sessionStorage.removeItem('asp_origin');
          document.location.href = OriginURL;
        }
        return;
      }
    } else {
      // Something went wrong. For now, just spit out the response as an alert.
      toast(await OAuthResponse.text());
    }
  }
  const session = await GET('/api/session');
  if (session.status === 403) { // No session set for this client yet, run the oauth process
    if (sessionStorageSupported()) {
      window.sessionStorage.setItem('asp_origin', document.location.href); // Store where we came from
    }
    // Construct OAuth URL and redirect to it
    const state = uuid();
    const OAuthURL = encodeURIComponent(`https://${document.location.hostname}/oauth.html?action=oauth&state=${state}`);
    document.location.href = `https://oauth.apache.org/auth?redirect_uri=${OAuthURL}&state=${state}`;
  } else if (session.status === 200) { // Found a working session
    const preferences = await session.json();
    if (callback) callback(preferences, QSDict);
  } else { // Something went wrong on the backend, spit out the error msg
    toast(await session.text());
  }
}


function blur_bg(blur= true) {
  const ctx = document.getElementById('contents');
  if (blur) {
    ctx.style.filter = "blur(5px)";
    ctx.style.userSelect = "none";
  } else {
    ctx.style.filter = "";
    ctx.style.userSelect = "auto";
  }
}

function toast(message, type="danger") {
  // Displays a message/alert as a toast if possible, falling back to alert() otherwise
  const toastdiv = document.getElementById('liveToast');
  if (toastdiv) {
    const toastobj = new bootstrap.Toast(toastdiv);
    toastdiv.querySelector('.toast-header').setAttribute('class', `toast-header text-white bg-${type}`);
    toastdiv.querySelector('.toast-body').innerText = message;
    toastobj.show();
    toastdiv.addEventListener('hide.bs.toast', () => blur_bg(false))
    blur_bg();
  } else {
    alert(message);
  }
}

/********* JIRA ACCOUNT FUNCTIONS *********/
async function jira_seed_project_list() {
  // Seeds the dropdown with current projects
  const projectlist = document.getElementById('project');
  const pubresp = await GET("/api/public");
  const pubdata = await pubresp.json();
  for (project of pubdata.projects) {
    const opt = document.createElement("option");
    opt.text = project;
    opt.value = project;
    projectlist.appendChild(opt);
  }
}

async function jira_account_request_submit(form) {
  const formdata = new FormData(form);
  if (formdata.get("verify") !== "agree") {
    toast("Please agree to sharing your data before submitting your request.");
    return false
  }
  const resp = await POST("/api/jira-account", {data: formdata});
  const result = await resp.json();
  if (!result.success) {
    toast(result.message);
    return false
  }
  const container = document.getElementById('contents');
  container.innerText = "Your request to create a Jira account has been submitted. Please check your email inbox for further information, as you will need to verify your email address."
  return false
}

async function jira_verify_email(token) {
  const resp = await GET(`/api/jira-account?token=${token}`);
  const result = await resp.json();
  const container = document.getElementById('verify_response');
  if (result.success) {
    container.innerText = "Your Jira account request has been successfully verified, and will be reviewed by the project you indicated. Please allow up to a few days for the project to review this request.";
  } else {
    container.innerText = "We were unable to verify your account token. If you feel this is in error, please let us know at: users@infra.apache.org."
    toast(result.message);
  }
}

async function jira_account_review(prefs, qs) {
  const token = qs.get("token");
  const resp = await GET(`/api/jira-account-review?token=${token}`);
  const result = await resp.json();
  if (!result.success) {
    toast(result.message);
  } else {
    const username = document.getElementById('username');
    username.value = result.entry.userid;
    const realname = document.getElementById('realname');
    realname.value = result.entry.realname;
    const why = document.getElementById('why');
    why.value = result.entry.why;
    const toktxt = document.getElementById('token');
    toktxt.value = token;
  }
}

async function jira_account_approve(form, verdict = "deny") {
  // Approve or deny a jira account request
  const data = new FormData(form)
  data.set("action", verdict);
  // Hide deny details panel and buttons
  const deny_details = document.getElementById('deny_details');
  deny_details.style.display = "none";
  const btns = document.getElementById('buttons_real');
  btns.style.display = "none";
  // Show spinner
  const spin = document.getElementById('buttons_spin');
  spin.style.display = "block";
  const resp = await POST("/api/jira-account-review", {data: data})
  const result = await resp.json();
  if (result.success) {
    const container = document.getElementById('contents');
    container.innerText = result.message;
  } else {
    toast(result.message);
    // Put back buttons, hide spinner
    btns.style.display = "block";
    spin.style.display = "none";
  }
}

function jira_account_deny_details() {
  const real_buttons = document.getElementById('buttons_real');
  real_buttons.style.display = "none";
  const deny_details = document.getElementById('deny_details');
  deny_details.style.display = "block";
}


async function mailinglist_seed_domain_list() {
  // Seeds the dropdown with current mailing list domains
  const domainlist = document.getElementById('domainpart');
  const pubresp = await GET("/api/public");
  const pubdata = await pubresp.json();
  for (const [project, domain] of Object.entries(pubdata.mail_domains)) {
    const opt = document.createElement("option");
    opt.text = domain;
    opt.value = domain;
    domainlist.appendChild(opt);
  }
}


function mailinglist_update_privacy(listpart, privatetick = false) {
  const span = document.getElementById('privacy_note');
  if (listpart == "private" || listpart == "security" || privatetick === true) {
    span.innerText = "This list will be PRIVATE";
    span.style.color = "maroon";
  } else {
    span.innerText = "This list will be PUBLIC.";
    span.style.color = "darkgreen";
  }
}


async function mailinglist_new(prefs) {
  await mailinglist_seed_domain_list();
  if (prefs.root) {
    const admindiv = document.getElementById('admin_div');
    admindiv.style.display = "block";
  }
}

async function mailinglist_new_submit(form) {
  const data = new FormData(form);
  const moderators = new Array();
  for (const modemail of data.get("moderators").split("\n")) {
    const email_trimmed = modemail.trim();
    if (email_trimmed.length > 4) {
      moderators.push(email_trimmed);
    }
  }
  const listpart = data.get("listpart");
  let is_private = data.get("private") === "yes";
  if (listpart == "private" || listpart == "security") {
    is_private = true;
  }
  const resp = await POST("/api/mailinglist", {
    json: {
      listpart: listpart,
      domainpart: data.get("domainpart"),
      moderators: moderators,
      muopts: data.get("muopts"),
      private: is_private,
      trailer: data.get("trailer") === "yes",
      expedited: data.get("expedited") === "yes"
    }
  });
  const result = await resp.json();
  if (result.success) {
    toast(result.message);
  } else {
    toast(result.message);
  }
}