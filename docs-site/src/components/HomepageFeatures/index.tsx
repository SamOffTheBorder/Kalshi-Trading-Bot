import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  description: ReactNode;
  to: string;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Backtest-first, by construction',
    description: (
      <>
        No strategy reaches paper or live trading without clearing a fee-adjusted
        bar on genuinely out-of-sample history. The train/test split is enforced
        by the engine, not left to discipline.
      </>
    ),
    to: '/docs/architecture/overview',
  },
  {
    title: 'Every run is honest, on purpose',
    description: (
      <>
        Four structural bugs were found and fixed by refusing to accept a
        good-looking backtest number without asking why — read the full
        run-by-run validation history.
      </>
    ),
    to: '/docs/status/validation-history',
  },
  {
    title: 'Gated, not aspirational',
    description: (
      <>
        Every phase — paper trading, dashboard, live money — has an explicit
        go/no-go gate. See what's done, what's blocked, and what's next.
      </>
    ),
    to: '/docs/roadmap',
  },
];

function Feature({title, description, to}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
        <Link to={to}>Read more &rarr;</Link>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
