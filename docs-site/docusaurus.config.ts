import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Kalshi Trading Bot',
  tagline: 'Backtest-first Kalshi event-contract trading, rebuilt from the ground up',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  // Local-only docs site for now; update if/when this is hosted somewhere.
  url: 'https://localhost',
  baseUrl: '/',

  organizationName: 'SamOffTheBorder',
  projectName: 'Kalshi-Trading-Bot',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/SamOffTheBorder/Kalshi-Trading-Bot/tree/main/docs-site/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Kalshi Trading Bot',
      logo: {
        alt: 'Kalshi Trading Bot',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          href: 'https://github.com/SamOffTheBorder/Kalshi-Trading-Bot',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Project',
          items: [
            {label: 'Overview', to: '/docs/intro'},
            {label: 'Scope & decisions', to: '/docs/project-scope'},
            {label: 'Validation status', to: '/docs/status/validation-history'},
            {label: 'Roadmap', to: '/docs/roadmap'},
          ],
        },
        {
          title: 'Operate',
          items: [
            {label: 'Fetch historical data', to: '/docs/runbooks/fetch-historical-data'},
            {label: 'Run a backtest', to: '/docs/runbooks/run-a-backtest'},
            {label: 'Archiver operations', to: '/docs/runbooks/archiver-operations'},
          ],
        },
        {
          title: 'Source',
          items: [
            {
              label: 'GitHub repo',
              href: 'https://github.com/SamOffTheBorder/Kalshi-Trading-Bot',
            },
          ],
        },
      ],
      copyright: 'Kalshi Trading Bot — internal project docs. Built with Docusaurus.',
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
